#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import logging
import os
import time
from dataclasses import dataclass
from multiprocessing import Event, Process, Queue
from types import SimpleNamespace
from typing import List, Optional

from charms.kafka.client import KafkaClient
from kafka.admin import NewTopic
from kafka.consumer.fetcher import ConsumerRecord
from kafka.errors import KafkaError
from pytest_operator.plugin import OpsTest
from tenacity import (
    RetryError,
    Retrying,
    retry,
    stop_after_attempt,
    wait_fixed,
    wait_random,
)

from integration.helpers import APP_NAME, DUMMY_NAME, get_provider_data

logger = logging.getLogger(__name__)
logging.getLogger("kafka.conn").disabled = True


@dataclass
class ContinuousWritesResult:
    count: int
    last_expected_message: int
    consumed_messages: Optional[List[ConsumerRecord]]


class ContinuousWrites:
    """Utility class for managing continuous writes."""

    TOPIC_NAME = "ha-test-topic"
    LAST_WRITTEN_VAL_PATH = "/tmp/last_written_value"

    def __init__(self, ops_test: OpsTest, app: str):
        self._ops_test = ops_test
        self._app = app
        self._is_stopped = True
        self._event = None
        self._queue = None
        self._process = None

    @retry(
        wait=wait_fixed(wait=5) + wait_random(0, 5),
        stop=stop_after_attempt(5),
    )
    def start(self) -> None:
        """Run continuous writes in the background."""
        if not self._is_stopped:
            self.clear()

        # create topic
        self._create_replicated_topic()

        # create process
        self._create_process()

        # pass the model full name to the process once it starts
        self.update()

        # start writes
        self._process.start()

    def update(self):
        """Update cluster related conf. Useful in cases such as scaling, pwd change etc."""
        self._queue.put(SimpleNamespace(model_full_name=self._ops_test.model.info.name))

    @retry(
        wait=wait_fixed(wait=5) + wait_random(0, 5),
        stop=stop_after_attempt(5),
    )
    def clear(self) -> None:
        """Stop writes and delete the topic."""
        if not self._is_stopped:
            self.stop()

        client = self._client()
        try:
            client.delete_topics(topics=[self.TOPIC_NAME])
        finally:
            client.close()

    def consumed_messages(self) -> List[ConsumerRecord] | None:
        """Consume the messages in the topic."""
        client = self._client()
        try:
            for attempt in Retrying(stop=stop_after_attempt(5), wait=wait_fixed(5)):
                with attempt:
                    client.subscribe_to_topic(topic_name=self.TOPIC_NAME)
                    # FIXME: loading whole list of consumed messages into memory might not be the best idea
                    return list(client.messages())
        except RetryError:
            logger.error("Could not get consumed messages from Kafka.")
            return []
        finally:
            client.close()

    def _create_replicated_topic(self):
        """Create topic with replication_factor = 3."""
        client = self._client()
        topic_config = NewTopic(
            name=self.TOPIC_NAME,
            num_partitions=1,
            replication_factor=3,
        )
        client.create_topic(topic=topic_config)
        logger.info(f"Created topic {self.TOPIC_NAME}")

    @retry(
        wait=wait_fixed(wait=5) + wait_random(0, 5),
        stop=stop_after_attempt(5),
    )
    def stop(self) -> ContinuousWritesResult:
        """Stop the continuous writes process and return max inserted ID."""
        if not self._is_stopped:
            self._stop_process()

        # messages count
        consumed_messages = self.consumed_messages()
        message_list = [record.value.decode() for record in consumed_messages]
        count = len(set(message_list))

        # last expected message stored on disk
        with open(ContinuousWrites.LAST_WRITTEN_VAL_PATH, "r") as f:
            last_expected_message = int(f.read().strip())

        logger.info(
            f"\n\nSTOP RESULTS:\n\t- Count: {count}\n\t- Last expected message: {last_expected_message}\n\t- Consumed messages: {message_list}\n"
        )
        return ContinuousWritesResult(count, last_expected_message, consumed_messages)

    def _create_process(self):
        self._is_stopped = False
        self._event = Event()
        self._queue = Queue()
        self._process = Process(
            target=ContinuousWrites._run_async,
            name="continuous_writes",
            args=(self._event, self._queue, 0, self._ops_test),
        )

    def _stop_process(self):
        self._event.set()
        self._process.join()
        self._queue.close()
        self._is_stopped = True

    def _client(self):
        """Build a Kafka client."""
        relation_data = get_provider_data(
            ops_test=self._ops_test,
            unit_name=f"{DUMMY_NAME}/0",
            owner=APP_NAME,
        )
        return KafkaClient(
            servers=relation_data["endpoints"].split(","),
            username=relation_data["username"],
            password=relation_data["password"],
            security_protocol="SASL_PLAINTEXT",
        )

    @staticmethod
    async def _run(
        event: Event, data_queue: Queue, starting_number: int, ops_test: OpsTest
    ) -> None:  # noqa: C901
        """Continuous writing."""

        def _client():
            """Build a Kafka client."""
            relation_data = get_provider_data(
                ops_test=ops_test,
                unit_name=f"{DUMMY_NAME}/0",
                owner=APP_NAME,
            )
            return KafkaClient(
                servers=relation_data["endpoints"].split(","),
                username=relation_data["username"],
                password=relation_data["password"],
                security_protocol="SASL_PLAINTEXT",
            )

        write_value = starting_number
        client = _client()

        while True:
            if not data_queue.empty():  # currently evaluates to false as we don't make updates
                data_queue.get(False)
                client.close()
                client = _client()

            ContinuousWrites._produce_message(client=client, write_value=write_value)
            await asyncio.sleep(0.1)

            # process termination requested
            if event.is_set():
                break

            write_value += 1

        # write last expected written value on disk
        with open(ContinuousWrites.LAST_WRITTEN_VAL_PATH, "w") as f:
            f.write(f"{str(write_value)}")
            os.fsync(f)

        try:
            client.close()
        except KafkaError:
            pass

    @staticmethod
    def _produce_message(client: KafkaClient, write_value: int) -> None:
        ackd = False
        while not ackd:
            try:
                client.produce_message(
                    topic_name=ContinuousWrites.TOPIC_NAME,
                    message_content=str(write_value),
                    timeout=300,
                )
                ackd = True
            except KafkaError as e:
                logger.error(f"Error on 'Message #{write_value}' Kafka Producer: {e}")
                time.sleep(0.1)

    @staticmethod
    def _run_async(event: Event, data_queue: Queue, starting_number: int, ops_test: OpsTest):
        """Run async code."""
        asyncio.run(ContinuousWrites._run(event, data_queue, starting_number, ops_test))
