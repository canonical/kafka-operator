#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import logging
import os
from dataclasses import dataclass
from multiprocessing import Event, Process, Queue
from types import SimpleNamespace
from typing import Optional

from charms.kafka.v0.client import KafkaClient
from kafka.admin import NewTopic
from kafka.errors import KafkaTimeoutError
from pytest_operator.plugin import OpsTest
from tenacity import (
    RetryError,
    Retrying,
    retry,
    stop_after_attempt,
    wait_fixed,
    wait_random,
)

from integration.helpers import DUMMY_NAME, get_provider_data

logger = logging.getLogger(__name__)


@dataclass
class ContinuousWritesResult:
    count: int = -1
    last_message: Optional[object] = None
    last_expected_message: int = -1
    lost_messages: int = -1


class ContinuousWrites:
    """Utility class for managing continuous writes."""

    TOPIC_NAME = "ha-test-topic"
    LAST_WRITTEN_VAL_PATH = "last_written_value"

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
        self._queue.put(SimpleNamespace(model_full_name=self._ops_test.model_full_name))

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

    def consumed_messages(self) -> list | None:
        """Consume the messages in the topic."""
        client = self._client()
        try:
            for attempt in Retrying(stop=stop_after_attempt(5), wait=wait_fixed(5)):
                with attempt:
                    client.subscribe_to_topic(topic_name=self.TOPIC_NAME)
                    # FIXME: loading whole list of consumed messages into memory might not be the best idea
                    return list(client.messages())
        except RetryError:
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

    @retry(
        wait=wait_fixed(wait=5) + wait_random(0, 5),
        stop=stop_after_attempt(5),
    )
    def stop(self) -> ContinuousWritesResult:
        """Stop the continuous writes process and return max inserted ID."""
        if not self._is_stopped:
            self._stop_process()

        result = ContinuousWritesResult()

        # messages count
        consumed_messages = self.consumed_messages()
        result.count = len(consumed_messages)
        result.last_message = consumed_messages[-1]

        # last expected message stored on disk
        with open(ContinuousWrites.LAST_WRITTEN_VAL_PATH, "r") as f:
            result.last_expected_message, result.lost_messages = map(
                int, f.read().rstrip().split(",", maxsplit=2)
            )

        return result

    def _create_process(self):
        self._is_stopped = False
        self._event = Event()
        self._queue = Queue()
        self._process = Process(
            target=ContinuousWrites._run_async,
            name="continuous_writes",
            args=(self._event, self._queue, 0),
        )

    def _stop_process(self):
        self._event.set()
        self._process.join()
        self._queue.close()
        self._is_stopped = True

    def _client(self):
        """Build a Kafka client."""
        relation_data = get_provider_data(
            unit_name=f"{DUMMY_NAME}/0",
            model_full_name=self._ops_test.model_full_name,
            endpoint="kafka-client-admin",
        )
        return KafkaClient(
            servers=relation_data["endpoints"].split(","),
            username=relation_data["username"],
            password=relation_data["password"],
            security_protocol="SASL_PLAINTEXT",
        )

    @staticmethod
    async def _run(event: Event, data_queue: Queue, starting_number: int) -> None:  # noqa: C901
        """Continuous writing."""
        initial_data = data_queue.get(True)

        def _client():
            """Build a Kafka client."""
            relation_data = get_provider_data(
                unit_name=f"{DUMMY_NAME}/0",
                model_full_name=initial_data.model_full_name,
                endpoint="kafka-client-admin",
            )
            return KafkaClient(
                servers=relation_data["endpoints"].split(","),
                username=relation_data["username"],
                password=relation_data["password"],
                security_protocol="SASL_PLAINTEXT",
            )

        write_value = starting_number
        lost_messages = 0
        client = _client()

        while True:
            if not data_queue.empty():  # currently evaluates to false as we don't make updates
                data_queue.get(False)
                client.close()
                client = _client()

            try:
                client.produce_message(
                    topic_name=ContinuousWrites.TOPIC_NAME, message_content=str(write_value)
                )
            except KafkaTimeoutError:
                client.close()
                client = _client()
                lost_messages += 1
            finally:
                # process termination requested
                if event.is_set():
                    break

            write_value += 1

        # write last expected written value on disk
        with open(ContinuousWrites.LAST_WRITTEN_VAL_PATH, "w") as f:
            f.write(f"{str(write_value)},{str(lost_messages)}")
            os.fsync(f)

        client.close()

    @staticmethod
    def _run_async(event: Event, data_queue: Queue, starting_number: int):
        """Run async code."""
        asyncio.run(ContinuousWrites._run(event, data_queue, starting_number))
