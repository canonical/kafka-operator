#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""KafkaClient class library for basic client connections to a Kafka Charm cluster.

`KafkaClient` provides an interface from which to make generic client connections
to a running Kafka Charm cluster. This can be as an administrator, producer or consumer,
provided that the necessary ACLs and user credentials have already been created.

Charms using this library are expected to have related to the target Kafka cluster,
and can use this library to streamline basic use-cases, e.g 'create a topic', 'produce a message
to a topic' or 'consume all messages from a topic'.

Example usage for charms using `KafkaClient`:

```python
# for a producer application

def on_kafka_relation_created(self, event: RelationCreatedEvent):
    client = KafkaClient(
        servers=event.relation.data[self.app].get("bootstrap-server", "").split(","),
        username=event.relation.data[self.app].get("username", ""),
        password=event.relation.data[self.app].get("password", ""),
        topic=event.relation.data[event.app].get("topic", ""),
        consumer_group_prefix=event.relation.data[event.app].get("consumer-group-prefix", None),
        security_protocol="SASL_PLAINTEXT",  # SASL_SSL for TLS enabled Kafka clusters
        replication_factor=3,
    )

    # if topic has not yet been created
    if "admin" in event.relation.data[event.app].get("extra-user-roles", ""):
        topic = NewTopic(
            name=client.topic,
            num_partitions=5,
            replication_factor=3,
        )
        client.create_topic(topic=topic)

    for message in SOME_ITERABLE:
        client.produce_message(message_content=message)

# OR
# for a consumer application

def on_kafka_relation_created(self, event: RelationCreatedEvent):
    client = KafkaClient(
        servers=event.relation.data[self.app].get("bootstrap-server", "").split(","),
        username=event.relation.data[self.app].get("username", ""),
        password=event.relation.data[self.app].get("password", ""),
        topic=event.relation.data[event.app].get("topic", ""),
        consumer_group_prefix=event.relation.data[event.app].get("consumer-group-prefix", None),
        security_protocol="SASL_PLAINTEXT",  # SASL_SSL for TLS enabled Kafka clusters
        replication_factor=3,
    )

    for message in client.messages:
        logger.info(message)
```
"""

import argparse
import logging
import sys
from functools import cached_property
from typing import Generator, List, Optional

from kafka import KafkaAdminClient, KafkaConsumer, KafkaProducer
from kafka.admin import NewTopic

logger = logging.getLogger(__name__)
logging.basicConfig(stream=sys.stdout, level=logging.INFO)

# The unique Charmhub library identifier, never change it
LIBID = "67b2f3f3cefa49e9b225346049625251"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1


class KafkaClient:
    """Simplistic KafkaClient built on top of kafka-python."""

    API_VERSION = (2, 5, 0)

    def __init__(
        self,
        servers: List[str],
        username: Optional[str],
        password: Optional[str],
        topic: str,
        consumer_group_prefix: Optional[str],
        security_protocol: str,
        cafile_path: Optional[str] = None,
        certfile_path: Optional[str] = None,
        keyfile_path: Optional[str] = None,
        replication_factor: int = 3,
    ) -> None:
        self.servers = servers
        self.username = username
        self.password = password
        self.topic = topic
        self.consumer_group_prefix = consumer_group_prefix
        self.security_protocol = security_protocol
        self.cafile_path = cafile_path
        self.certfile_path = certfile_path
        self.keyfile_path = keyfile_path
        self.replication_factor = replication_factor

        self.sasl = "SASL" in self.security_protocol
        self.ssl = "SSL" in self.security_protocol
        self.mtls = self.security_protocol == "SSL"

    @cached_property
    def _admin_client(self) -> KafkaAdminClient:
        """Initialises and caches a `KafkaAdminClient`."""
        return KafkaAdminClient(
            client_id=self.username,
            bootstrap_servers=self.servers,
            ssl_check_hostname=False,
            security_protocol=self.security_protocol,
            sasl_plain_username=self.username if self.sasl else None,
            sasl_plain_password=self.password if self.sasl else None,
            sasl_mechanism="SCRAM-SHA-512" if self.sasl else None,
            ssl_cafile=self.cafile_path if self.ssl else None,
            ssl_certfile=self.certfile_path if self.ssl else None,
            ssl_keyfile=self.keyfile_path if self.mtls else None,
            api_version=KafkaClient.API_VERSION if self.mtls else None,
        )

    @cached_property
    def _producer_client(self) -> KafkaProducer:
        """Initialises and caches a `KafkaProducer`."""
        return KafkaProducer(
            bootstrap_servers=self.servers,
            ssl_check_hostname=False,
            security_protocol=self.security_protocol,
            sasl_plain_username=self.username if self.sasl else None,
            sasl_plain_password=self.password if self.sasl else None,
            sasl_mechanism="SCRAM-SHA-512" if self.sasl else None,
            ssl_cafile=self.cafile_path if self.ssl else None,
            ssl_certfile=self.certfile_path if self.ssl else None,
            ssl_keyfile=self.keyfile_path if self.mtls else None,
            api_version=KafkaClient.API_VERSION if self.mtls else None,
        )

    @cached_property
    def _consumer_client(self) -> KafkaConsumer:
        """Initialises and caches a `KafkaConsumer`."""
        return KafkaConsumer(
            self.topic,
            bootstrap_servers=self.servers,
            ssl_check_hostname=False,
            security_protocol=self.security_protocol,
            sasl_plain_username=self.username if self.sasl else None,
            sasl_plain_password=self.password if self.sasl else None,
            sasl_mechanism="SCRAM-SHA-512" if self.sasl else None,
            ssl_cafile=self.cafile_path if self.ssl else None,
            ssl_certfile=self.certfile_path if self.ssl else None,
            ssl_keyfile=self.keyfile_path if self.mtls else None,
            api_version=KafkaClient.API_VERSION if self.mtls else None,
            group_id=self.consumer_group_prefix + "1" if self.consumer_group_prefix else None,
            enable_auto_commit=True,
            auto_offset_reset="earliest",
            consumer_timeout_ms=15000,
        )

    def create_topic(self, topic: NewTopic) -> None:
        """Creates a new topic on the Kafka cluster.

        Args:
            topic: the configuration of the topic to create
        """
        self._admin_client.create_topics(new_topics=[topic], validate_only=False)

    def messages(self) -> Generator:
        """Iterable of consumer messages.

        Returns:
            Generator of messages
        """
        yield from self._consumer_client

    def produce_message(self, message_content: str) -> None:
        """Sends message to target topic on the cluster.

        Args:
            message_content: the content of the message to send
        """
        item_content = f"Message #{message_content}"
        future = self._producer_client.send(self.topic, str.encode(item_content))
        future.get(timeout=60)
        logger.info(f"Message published to topic={self.topic}, message content: {item_content}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Handler for running a Kafka client")
    parser.add_argument(
        "-t",
        "--topic",
        help="Kafka topic provided by Kafka Charm",
        type=str,
        default="hot-topic",
    )
    parser.add_argument(
        "-u",
        "--username",
        help="Kafka username provided by Kafka Charm",
        type=str,
    )
    parser.add_argument(
        "-p",
        "--password",
        help="Kafka password provided by Kafka Charm",
        type=str,
    )
    parser.add_argument(
        "-c",
        "--consumer-group-prefix",
        help="Kafka consumer-group-prefix provided by Kafka Charm",
        type=str,
    )
    parser.add_argument(
        "-s",
        "--servers",
        help="comma delimited list of Kafka bootstrap-server strings",
        type=str,
    )
    parser.add_argument(
        "-x",
        "--security-protocol",
        help="security protocol used for authentication",
        type=str,
        default="SASL_PLAINTEXT",
    )
    parser.add_argument(
        "-n",
        "--num-messages",
        help="number of messages to send from a producer",
        type=int,
        default=15,
    )
    parser.add_argument(
        "-r",
        "--replication-factor",
        help="replcation.factor for created topics",
        type=int,
    )
    parser.add_argument("--producer", action="store_true", default=False)
    parser.add_argument("--consumer", action="store_true", default=False)
    parser.add_argument("--cafile-path", type=str)
    parser.add_argument("--certfile-path", type=str)
    parser.add_argument("--keyfile-path", type=str)

    args = parser.parse_args()
    servers = args.servers.split(",")
    if not args.consumer_group_prefix:
        args.consumer_group_prefix = f"{args.username}-" if args.username else None

    client = KafkaClient(
        servers=servers,
        username=args.username,
        password=args.password,
        topic=args.topic,
        consumer_group_prefix=args.consumer_group_prefix,
        security_protocol=args.security_protocol,
        cafile_path=args.cafile_path,
        certfile_path=args.certfile_path,
        keyfile_path=args.keyfile_path,
        replication_factor=args.replication_factor,
    )

    if args.producer:
        logger.info(f"Creating new topic - {args.topic}")

        topic = NewTopic(
            name=args.topic,
            num_partitions=args.num_partitions,
            replication_factor=args.replication_factor,
        )
        client.create_topic(topic=topic)

        logger.info("--producer - Starting...")
        for i in range(args.num_messages):
            client.produce_message(message_content=str(i))

    if args.consumer:
        logger.info("--consumer - Starting...")
        for message in client.messages():
            logger.info(message)

    else:
        logger.info("No client type args found. Exiting...")
        exit(1)
