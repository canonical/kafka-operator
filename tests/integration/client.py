#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import argparse
import logging
import sys
import time
from typing import List, Optional

from kafka import KafkaAdminClient, KafkaConsumer, KafkaProducer
from kafka.admin import NewTopic

logger = logging.getLogger(__name__)
logging.basicConfig(stream=sys.stdout, level=logging.INFO)


class KafkaClient:

    API_VERSION = (2, 5, 0)

    def __init__(
        self,
        servers: List[str],
        username: Optional[str],
        password: Optional[str],
        topic: str,
        consumer_group_prefix: Optional[str],
        security_protocol: str,
    ) -> None:
        self.servers = servers
        self.username = username
        self.password = password
        self.topic = topic
        self.consumer_group_prefix = consumer_group_prefix
        self.security_protocol = security_protocol

        self.sasl = "SASL" in self.security_protocol
        self.ssl = "SSL" in self.security_protocol
        self.mtls = self.security_protocol == "SSL"

    def create_topic(self):
        admin_client = KafkaAdminClient(
            client_id=self.username,
            bootstrap_servers=self.servers,
            ssl_check_hostname=False,
            security_protocol=self.security_protocol,
            sasl_plain_username=self.username if self.sasl else None,
            sasl_plain_password=self.password if self.sasl else None,
            sasl_mechanism="SCRAM-SHA-512" if self.sasl else None,
            ssl_cafile="certs/ca.pem" if self.ssl else None,
            ssl_certfile="certs/cert.pem" if self.ssl else None,
            ssl_keyfile="certs/key.pem" if self.mtls else None,
            api_version=KafkaClient.API_VERSION if self.mtls else None,
        )

        topic_list = [NewTopic(name=self.topic, num_partitions=5, replication_factor=1)]
        admin_client.create_topics(new_topics=topic_list, validate_only=False)

    def run_consumer(self):
        consumer = KafkaConsumer(
            self.topic,
            bootstrap_servers=self.servers,
            ssl_check_hostname=False,
            security_protocol=self.security_protocol,
            sasl_plain_username=self.username if self.sasl else None,
            sasl_plain_password=self.password if self.sasl else None,
            sasl_mechanism="SCRAM-SHA-512" if self.sasl else None,
            ssl_cafile="certs/ca.pem" if self.ssl else None,
            ssl_certfile="certs/cert.pem" if self.ssl else None,
            ssl_keyfile="certs/key.pem" if self.mtls else None,
            api_version=KafkaClient.API_VERSION if self.mtls else None,
            group_id=self.consumer_group_prefix + "1" if self.consumer_group_prefix else None,
            enable_auto_commit=True,
            auto_offset_reset="earliest",
            consumer_timeout_ms=15000,
        )

        for message in consumer:
            logger.info(str(message))

    def run_producer(self):
        producer = KafkaProducer(
            bootstrap_servers=self.servers,
            ssl_check_hostname=False,
            security_protocol=self.security_protocol,
            sasl_plain_username=self.username if self.sasl else None,
            sasl_plain_password=self.password if self.sasl else None,
            sasl_mechanism="SCRAM-SHA-512" if self.sasl else None,
            ssl_cafile="certs/ca.pem" if self.ssl else None,
            ssl_certfile="certs/cert.pem" if self.ssl else None,
            ssl_keyfile="certs/key.pem" if self.mtls else None,
            api_version=KafkaClient.API_VERSION if self.mtls else None,
        )

        for _ in range(3):
            logger.info("Generating messages to send... ")
            for i in range(5):

                item_content = f"Message #{i}"

                future = producer.send(self.topic, str.encode(item_content))
                future.get(timeout=60)
                logger.info(
                    f"Message published to topic={self.topic}, message content: {item_content}"
                )
                time.sleep(5)
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Handler for running a Kafka client")
    parser.add_argument(
        "-t",
        "--topic",
        help="Kafka topic provided by Kafka Charm",
        type=str,
        default="demo",
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

    parser.add_argument("--producer", action="store_true", default=False)
    parser.add_argument("--consumer", action="store_true", default=False)

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
    )

    if args.producer:
        logger.info(f"Creating new topic - {args.topic}")
        client.create_topic()
        logger.info("--producer - Starting...")
        producer = client.run_producer()
    if args.consumer:
        logger.info("--consumer - Starting...")
        consumer = client.run_consumer()
    else:
        logger.info("No client type args found. Exiting...")
