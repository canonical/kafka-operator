#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
from pathlib import Path
from subprocess import PIPE, check_output
from typing import Any, Dict

import yaml
from charms.kafka.v0.client import KafkaClient
from kafka.admin import NewTopic

from snap import KafkaSnap

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
ZK_NAME = "zookeeper"
REL_NAME_ADMIN = "kafka-client-admin"

logger = logging.getLogger(__name__)


def produce_and_check_logs(
    model_full_name: str, kafka_unit_name: str, provider_unit_name: str, topic: str
) -> None:
    """Produces messages from HN to chosen Kafka topic.

    Args:
        model_full_name: the full name of the model
        kafka_unit_name: the kafka unit to checks logs on
        provider_unit_name: the app to grab credentials from
        topic: the desired topic to produce to

    Raises:
        KeyError: if missing relation data
        AssertionError: if logs aren't found for desired topic
    """
    relation_data = get_provider_data(
        unit_name=provider_unit_name,
        model_full_name=model_full_name,
        endpoint="kafka-client-admin",
    )
    topic = topic
    username = relation_data.get("username", None)
    password = relation_data.get("password", None)
    servers = relation_data.get("endpoints", "").split(",")
    security_protocol = "SASL_PLAINTEXT"

    if not (username and password and servers):
        raise KeyError("missing relation data from app charm")

    client = KafkaClient(
        servers=servers,
        username=username,
        password=password,
        security_protocol=security_protocol,
    )
    topic_config = NewTopic(
        name=topic,
        num_partitions=5,
        replication_factor=1,
    )

    client.create_topic(topic=topic_config)
    for i in range(15):
        message = f"Message #{i}"
        client.produce_message(topic_name=topic, message_content=message)

    check_logs(model_full_name, kafka_unit_name, topic)


def check_logs(model_full_name: str, kafka_unit_name: str, topic: str) -> None:
    """Checks if messages for a topic have been produced.

    Args:
        model_full_name: the full name of the model
        kafka_unit_name: the kafka unit to checks logs on
        topic: the desired topic to check
    """
    logs = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh {kafka_unit_name} sudo -i 'find {KafkaSnap.DATA_PATH}/data'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    ).splitlines()

    logger.debug(f"{logs=}")

    passed = False
    for log in logs:
        if topic and "index" in log:
            passed = True
            break

    assert passed, "logs not found"


def get_provider_data(
    unit_name: str, model_full_name: str, endpoint: str = "kafka-client"
) -> Dict[str, str]:
    result = show_unit(unit_name=unit_name, model_full_name=model_full_name)
    relations_info = result[unit_name]["relation-info"]
    logger.info(f"Relation info: {relations_info}")
    provider_relation_data = {}
    for info in relations_info:
        if info["endpoint"] == endpoint:
            logger.info(f"Relation data: {info}")
            provider_relation_data["username"] = info["application-data"]["username"]
            provider_relation_data["password"] = info["application-data"]["password"]
            provider_relation_data["endpoints"] = info["application-data"]["endpoints"]
            provider_relation_data["zookeeper-uris"] = info["application-data"]["zookeeper-uris"]
            provider_relation_data["tls"] = info["application-data"]["tls"]
            if "consumer-group-prefix" in info["application-data"]:
                provider_relation_data["consumer-group-prefix"] = info["application-data"][
                    "consumer-group-prefix"
                ]
            provider_relation_data["topic"] = info["application-data"]["topic"]
    return provider_relation_data


def show_unit(unit_name: str, model_full_name: str) -> Any:
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju show-unit {unit_name}",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return yaml.safe_load(result)
