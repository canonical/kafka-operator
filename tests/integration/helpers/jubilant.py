#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import re
from pathlib import Path
from subprocess import PIPE, CalledProcessError, check_output
from typing import Any

import jubilant
import yaml
from charms.kafka.v0.client import KafkaClient
from kafka.admin import NewTopic
from tenacity import retry
from tenacity.stop import stop_after_attempt
from tenacity.wait import wait_fixed

from literals import (
    PATHS,
    PEER_CLUSTER_ORCHESTRATOR_RELATION,
    PEER_CLUSTER_RELATION,
)

from . import (
    APP_NAME,
    CONTROLLER_NAME,
    TEST_DEFAULT_MESSAGES,
    KRaftMode,
    KRaftUnitStatus,
)

logger = logging.getLogger(__name__)

BASE = "ubuntu@24.04"


def all_active_idle(status: jubilant.Status, *apps: str):
    """Helper function for jubilant all units active|idle checks."""
    return jubilant.all_agents_idle(status, *apps) and jubilant.all_active(status, *apps)


def deploy_cluster(
    juju: jubilant.Juju,
    charm: Path,
    kraft_mode: KRaftMode,
    series: str = "noble",
    config_broker: dict = {},
    config_controller: dict = {},
    num_broker: int = 1,
    num_controller: int = 1,
    storage_broker: dict = {},
    app_name_broker: str = str(APP_NAME),
    app_name_controller: str = CONTROLLER_NAME,
):
    """Deploys an Apache Kafka cluster using the Charmed Apache Kafka operator in KRaft mode."""
    logger.info(f"Deploying Kafka cluster in '{kraft_mode}' mode")

    base = "ubuntu@24.04" if series == "noble" else "ubuntu@22.04"

    juju.deploy(
        charm,
        app=app_name_broker,
        num_units=num_broker,
        base=base,
        storage=storage_broker,
        config={
            "roles": "broker,controller" if kraft_mode == "single" else "broker",
            "profile": "testing",
        }
        | config_broker,
        trust=True,
    )

    if kraft_mode == "multi":
        juju.deploy(
            charm,
            app=app_name_controller,
            num_units=num_controller,
            base=base,
            config={
                "roles": "controller",
                "profile": "testing",
            }
            | config_controller,
            trust=True,
        )

    assert_status_func = jubilant.all_active if kraft_mode == "single" else jubilant.all_blocked
    apps = [app_name_broker] if kraft_mode == "single" else [app_name_broker, app_name_controller]

    juju.wait(
        lambda status: jubilant.all_agents_idle(status, *apps)
        and assert_status_func(status, *apps),
        delay=3,
        successes=10,
        timeout=1800,
    )

    if kraft_mode == "multi":
        juju.integrate(
            f"{app_name_broker}:{PEER_CLUSTER_ORCHESTRATOR_RELATION}",
            f"{app_name_controller}:{PEER_CLUSTER_RELATION}",
        )

    juju.wait(
        lambda status: all_active_idle(status, *apps),
        delay=3,
        successes=10,
        timeout=1800,
    )


def get_unit_ipv4_address(model_full_name: str | None, unit_name: str) -> str | None:
    """A safer alternative for `juju.unit.get_public_address()` which is robust to network changes."""
    try:
        stdout = check_output(
            f"JUJU_MODEL={model_full_name} juju ssh {unit_name} hostname -i",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )
    except CalledProcessError:
        return None

    ipv4_matches = re.findall(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}", stdout)

    if ipv4_matches:
        return ipv4_matches[0]

    return None


def show_unit(model: str, unit_name: str) -> Any:
    result = check_output(
        f"JUJU_MODEL={model} juju show-unit {unit_name}",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return yaml.safe_load(result)


def get_secret_by_label(juju: jubilant.Juju, label: str, owner: str) -> dict[str, str]:
    secrets_meta_raw = check_output(
        f"JUJU_MODEL={juju.model} juju list-secrets --format json",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    ).strip()
    secrets_meta = json.loads(secrets_meta_raw)

    for secret_id in secrets_meta:
        if owner and not secrets_meta[secret_id]["owner"] == owner:
            continue
        if secrets_meta[secret_id]["label"] == label:
            break

    secrets_data_raw = check_output(
        f"JUJU_MODEL={juju.model} juju show-secret --format json --reveal {secret_id}",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    secret_data = json.loads(secrets_data_raw)
    return secret_data[secret_id]["content"]["Data"]


def get_provider_data(
    model: str,
    owner: str,
    unit_name: str,
    relation_name: str = "kafka-client",
    relation_interface: str = "kafka-client-admin",
) -> dict[str, str]:
    _juju = jubilant.Juju(model=model)

    unit_data = show_unit(model, unit_name)

    provider_relation_data = {}
    for info in unit_data[unit_name]["relation-info"]:
        if info["endpoint"] == relation_interface:
            provider_relation_data["relation-id"] = info["relation-id"]

            # initially collects all non-secret keys
            provider_relation_data.update(dict(info["application-data"]))

    user_secret = get_secret_by_label(
        _juju,
        label=f"{relation_name}.{provider_relation_data['relation-id']}.user.secret",
        owner=owner,
    )

    tls_secret = get_secret_by_label(
        _juju,
        label=f"{relation_name}.{provider_relation_data['relation-id']}.tls.secret",
        owner=owner,
    )

    # overrides to secret keys if found
    return provider_relation_data | user_secret | tls_secret


def produce_and_check_logs(
    juju: jubilant.Juju,
    kafka_unit_name: str,
    provider_unit_name: str,
    topic: str,
    create_topic: bool = True,
    replication_factor: int = 1,
    num_partitions: int = 5,
) -> None:
    """Produces 15 messages from HN to chosen Kafka topic.

    Args:
        juju: Jubilant juju fixture
        kafka_unit_name: the kafka unit to checks logs on
        provider_unit_name: the app to grab credentials from
        topic: the desired topic to produce to
        create_topic: if the topic needs to be created
        replication_factor: replication factor of the created topic
        num_partitions: number of partitions for the topic

    Raises:
        KeyError: if missing relation data
        AssertionError: if logs aren't found for desired topic
    """
    assert juju.model
    relation_data = get_provider_data(
        model=juju.model,
        unit_name=provider_unit_name,
        owner=APP_NAME,
    )
    client = KafkaClient(
        servers=relation_data["endpoints"].split(","),
        username=relation_data["username"],
        password=relation_data["password"],
        security_protocol="SASL_PLAINTEXT",
    )

    if create_topic:
        topic_config = NewTopic(
            name=topic,
            num_partitions=num_partitions,
            replication_factor=replication_factor,
        )
        client.create_topic(topic=topic_config)

    for i in range(TEST_DEFAULT_MESSAGES):
        message = f"Message #{i}"
        client.produce_message(topic_name=topic, message_content=message)

    check_logs(juju, kafka_unit_name, topic)


def check_logs(juju: jubilant.Juju, kafka_unit_name: str, topic: str) -> None:
    """Checks if messages for a topic have been produced.

    Args:
        juju: Jubilant juju fixture
        kafka_unit_name: the kafka unit to checks logs on
        topic: the desired topic to check
    """
    logs = check_output(
        f"JUJU_MODEL={juju.model} juju ssh {kafka_unit_name} sudo -i 'find {PATHS['kafka']['DATA']}/data'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    ).splitlines()

    passed = False
    for log in logs:
        if topic in log and "index" in log:
            passed = True
            break

    assert passed, "logs not found"


@retry(
    wait=wait_fixed(20),
    stop=stop_after_attempt(6),
    reraise=True,
)
def kraft_quorum_status(
    juju: jubilant.Juju, unit_name: str, bootstrap_controller: str, verbose: bool = True
) -> dict[int, KRaftUnitStatus]:
    """Returns a dict mapping of unit ID to KRaft unit status based on `kafka-metadata-quorum.sh` utility's output."""
    result = check_output(
        f"JUJU_MODEL={juju.model} juju ssh {unit_name} sudo -i 'charmed-kafka.metadata-quorum  --command-config {PATHS['kafka']['CONF']}/server.properties --bootstrap-controller {bootstrap_controller} describe --replication'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )
    # parse `kafka-metadata-quorum.sh` output
    # NodeId  DirectoryId  LogEndOffset  Lag  LastFetchTimestamp  LastCaughtUpTimestamp  Status
    unit_status: dict[int, str] = {}
    for line in result.split("\n"):
        fields = [c.strip() for c in line.split("\t")]
        try:
            unit_status[int(fields[0])] = KRaftUnitStatus(fields[6])
        except (ValueError, IndexError):
            continue

    if verbose:
        print(unit_status)

    return unit_status
