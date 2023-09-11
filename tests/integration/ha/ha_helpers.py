#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import re
from subprocess import PIPE, check_output

from pytest_operator.plugin import OpsTest

from integration.helpers import APP_NAME, get_address
from literals import SECURITY_PROTOCOL_PORTS
from snap import KafkaSnap

PROCESS = "kafka.Kafka"

logger = logging.getLogger(__name__)


async def get_topic_leader(ops_test: OpsTest, topic: str) -> int:
    """Get the broker with the topic leader.

    Args:
        ops_test: OpsTest utility class
        topic: the desired topic to check
    """
    bootstrap_server = (
        await get_address(ops_test=ops_test)
        + f":{SECURITY_PROTOCOL_PORTS['SASL_PLAINTEXT'].client}"
    )

    result = check_output(
        f"JUJU_MODEL={ops_test.model_full_name} juju ssh kafka/0 sudo -i 'charmed-kafka.topics --bootstrap-server {bootstrap_server} --command-config {KafkaSnap.CONF_PATH}/client.properties --describe --topic {topic}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return re.search(r"Leader: (\d+)", result)[1]


async def get_topic_offsets(ops_test: OpsTest, topic: str, unit_name: str) -> list[str]:
    """Get the offsets of a topic on a unit.

    Args:
        ops_test: OpsTest utility class
        topic: the desired topic to check
        unit_name: unit to check the offsets on
    """
    bootstrap_server = (
        await get_address(ops_test=ops_test)
        + f":{SECURITY_PROTOCOL_PORTS['SASL_PLAINTEXT'].client}"
    )

    # example of topic offset output: 'test-topic:0:10'
    result = check_output(
        f"JUJU_MODEL={ops_test.model_full_name} juju ssh {unit_name} sudo -i 'charmed-kafka.get-offsets --bootstrap-server {bootstrap_server} --command-config {KafkaSnap.CONF_PATH}/client.properties --topic {topic}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return re.search(rf"{topic}:(\d+:\d+)", result)[1].split(":")


async def send_control_signal(
    ops_test: OpsTest, unit_name: str, kill_code: str, app_name: str = APP_NAME
) -> None:
    if len(ops_test.model.applications[app_name].units) < 3:
        await ops_test.model.applications[app_name].add_unit(count=1)
        await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)

    kill_cmd = f"exec --unit {unit_name} -- pkill --signal {kill_code} -f {PROCESS}"
    return_code, _, _ = await ops_test.juju(*kill_cmd.split())

    if return_code != 0:
        raise Exception(
            f"Expected kill command {kill_cmd} to succeed instead it failed: {return_code}"
        )
