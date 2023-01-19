#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import re
import socket
from contextlib import closing
from pathlib import Path
from subprocess import PIPE, check_output
from typing import Any, Dict, List, Set, Tuple

import yaml
from charms.kafka.v0.client import KafkaClient
from kafka.admin import NewTopic
from pytest_operator.plugin import OpsTest

from auth import Acl, KafkaAuth
from snap import SNAP_CONFIG_PATH

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
ZK_NAME = "zookeeper"

logger = logging.getLogger(__name__)


def load_acls(model_full_name: str, zookeeper_uri: str) -> Set[Acl]:
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh kafka/0 'kafka.acls --authorizer-properties zookeeper.connect={zookeeper_uri} --list'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return KafkaAuth._parse_acls(acls=result)


def load_super_users(model_full_name: str) -> List[str]:
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh kafka/0 'cat /var/snap/kafka/common/server.properties'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )
    properties = result.splitlines()

    for prop in properties:
        if "super.users" in prop:
            return prop.split("=")[1].split(";")

    return []


def check_user(model_full_name: str, username: str, zookeeper_uri: str) -> None:
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh kafka/0 'kafka.configs --zookeeper {zookeeper_uri} --describe --entity-type users --entity-name {username}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )
    assert "SCRAM-SHA-512" in result


def get_user(model_full_name: str, username: str, zookeeper_uri: str) -> str:
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh kafka/0 'kafka.configs --zookeeper {zookeeper_uri} --describe --entity-type users --entity-name {username}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return result


def show_unit(unit_name: str, model_full_name: str) -> Any:
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju show-unit {unit_name}",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return yaml.safe_load(result)


def get_zookeeper_connection(unit_name: str, model_full_name: str) -> Tuple[List[str], str]:
    result = show_unit(unit_name=unit_name, model_full_name=model_full_name)

    relations_info = result[unit_name]["relation-info"]

    usernames = []
    zookeeper_uri = ""
    for info in relations_info:
        if info["endpoint"] == "cluster":
            for key in info["application-data"].keys():
                if re.match(r"(relation\-[\d]+)", key):
                    usernames.append(key)
        if info["endpoint"] == "zookeeper":
            zookeeper_uri = info["application-data"]["uris"]

    if zookeeper_uri and usernames:
        return usernames, zookeeper_uri
    else:
        raise Exception("config not found")


def get_kafka_zk_relation_data(unit_name: str, model_full_name: str) -> Dict[str, str]:
    result = show_unit(unit_name=unit_name, model_full_name=model_full_name)
    relations_info = result[unit_name]["relation-info"]

    zk_relation_data = {}
    for info in relations_info:
        if info["endpoint"] == "zookeeper":
            zk_relation_data["chroot"] = info["application-data"]["chroot"]
            zk_relation_data["endpoints"] = info["application-data"]["endpoints"]
            zk_relation_data["password"] = info["application-data"]["password"]
            zk_relation_data["uris"] = info["application-data"]["uris"]
            zk_relation_data["username"] = info["application-data"]["username"]
            zk_relation_data["tls"] = info["application-data"]["tls"]
    return zk_relation_data


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
    return provider_relation_data


async def get_address(ops_test: OpsTest, app_name=APP_NAME, unit_num=0) -> str:
    """Get the address for a unit."""
    status = await ops_test.model.get_status()  # noqa: F821
    address = status["applications"][app_name]["units"][f"{app_name}/{unit_num}"]["public-address"]
    return address


async def set_password(ops_test: OpsTest, username="sync", password=None, num_unit=0) -> Any:
    """Use the charm action to start a password rotation."""
    params = {"username": username}
    if password:
        params["password"] = password

    action = await ops_test.model.units.get(f"{APP_NAME}/{num_unit}").run_action(
        "set-password", **params
    )
    password = await action.wait()
    return password.results


def check_socket(host: str, port: int) -> None:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        assert sock.connect_ex((host, port)) == 0


def check_tls(ip: str, port: int) -> None:
    result = check_output(
        f"echo | openssl s_client -connect {ip}:{port}",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    # FIXME: The server cannot be validated, we would need to try to connect using the CA
    # from self-signed certificates. This is indication enough that the server is sending a
    # self-signed key.
    assert "CN = kafka" in result


def produce_and_check_logs(
    model_full_name: str, kafka_unit_name: str, provider_unit_name: str, topic: str
) -> None:
    """Produces messages from HN to chosen Kafka topic.

    Args:
        model_full_name: the full name of the model
        kafka_unit_name: the kafka unit to checks logs on
        proider_unit_name: the app to grab credentials from
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
        topic=topic,
        consumer_group_prefix=None,
        security_protocol=security_protocol,
    )
    topic_config = NewTopic(
        name=client.topic,
        num_partitions=5,
        replication_factor=1,
    )

    client.create_topic(topic=topic_config)
    for i in range(15):
        message = f"Message #{i}"
        client.produce_message(message_content=message)

    logs = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh {kafka_unit_name} 'find /var/snap/kafka/common/log-data'",
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


async def run_client_properties(ops_test: OpsTest) -> str:
    """Runs command requiring admin permissions, authenticated with bootstrap-server."""
    bootstrap_server = await get_address(ops_test=ops_test) + ":9092"
    result = check_output(
        f"JUJU_MODEL={ops_test.model_full_name} juju ssh kafka/0 'kafka.configs --bootstrap-server {bootstrap_server} --describe --all --command-config {SNAP_CONFIG_PATH}/client.properties --entity-type users'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return result
