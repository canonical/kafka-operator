#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import re
from dataclasses import dataclass
from subprocess import PIPE, check_output

from pytest_operator.plugin import OpsTest

from integration.ha.continuous_writes import ContinuousWritesResult
from integration.helpers import APP_NAME, get_address, get_kafka_zk_relation_data
from literals import SECURITY_PROTOCOL_PORTS
from snap import KafkaSnap
from utils import get_active_brokers

PROCESS = "kafka.Kafka"
SERVICE_DEFAULT_PATH = "/etc/systemd/system/snap.charmed-kafka.daemon.service"


logger = logging.getLogger(__name__)


@dataclass
class TopicDescription:
    leader: int
    in_sync_replicas: set


class ProcessError(Exception):
    """Raised when a process fails."""


class ProcessRunningError(Exception):
    """Raised when a process is running when it is not expected to be."""


async def get_topic_description(ops_test: OpsTest, topic: str) -> TopicDescription:
    """Get the broker with the topic leader.

    Args:
        ops_test: OpsTest utility class
        topic: the desired topic to check
    """
    bootstrap_servers = []
    for unit in ops_test.model.applications[APP_NAME].units:
        bootstrap_servers.append(
            await get_address(ops_test=ops_test, unit_num=unit.name.split("/")[-1])
            + f":{SECURITY_PROTOCOL_PORTS['SASL_PLAINTEXT'].client}"
        )
    unit_name = ops_test.model.applications[APP_NAME].units[0].name

    output = check_output(
        f"JUJU_MODEL={ops_test.model_full_name} juju ssh {unit_name} sudo -i 'charmed-kafka.topics --bootstrap-server {','.join(bootstrap_servers)} --command-config {KafkaSnap.CONF_PATH}/client.properties --describe --topic {topic}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    leader = int(re.search(r"Leader: (\d+)", output)[1])
    in_sync_replicas = {int(i) for i in re.search(r"Isr: ([\d,]+)", output)[1].split(",")}

    return TopicDescription(leader, in_sync_replicas)


async def get_topic_offsets(ops_test: OpsTest, topic: str) -> list[str]:
    """Get the offsets of a topic on a unit.

    Args:
        ops_test: OpsTest utility class
        topic: the desired topic to check
    """
    bootstrap_servers = []
    for unit in ops_test.model.applications[APP_NAME].units:
        bootstrap_servers.append(
            await get_address(ops_test=ops_test, unit_num=unit.name.split("/")[-1])
            + f":{SECURITY_PROTOCOL_PORTS['SASL_PLAINTEXT'].client}"
        )
    unit_name = ops_test.model.applications[APP_NAME].units[0].name

    # example of topic offset output: 'test-topic:0:10'
    result = check_output(
        f"JUJU_MODEL={ops_test.model_full_name} juju ssh {unit_name} sudo -i 'charmed-kafka.get-offsets --bootstrap-server {','.join(bootstrap_servers)} --command-config {KafkaSnap.CONF_PATH}/client.properties --topic {topic}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return re.search(rf"{topic}:(\d+:\d+)", result)[1].split(":")


async def send_control_signal(
    ops_test: OpsTest, unit_name: str, signal: str, app_name: str = APP_NAME
) -> None:
    if len(ops_test.model.applications[app_name].units) < 3:
        await ops_test.model.applications[app_name].add_unit(count=1)
        await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)

    kill_cmd = f"exec --unit {unit_name} -- pkill --signal {signal} -f {PROCESS}"
    return_code, stdout, stderr = await ops_test.juju(*kill_cmd.split())

    if return_code != 0:
        raise Exception(
            f"Expected kill command {kill_cmd} to succeed instead it failed: {return_code}, {stdout}, {stderr}"
        )


async def patch_restart_delay(ops_test: OpsTest, unit_name: str, delay: int) -> None:
    """Adds a restart delay in the DB service file.

    When the DB service fails it will now wait for `delay` number of seconds.
    """
    add_delay_cmd = (
        f"exec --unit {unit_name} -- "
        f"sudo sed -i -e '/^[Service]/a RestartSec={delay}' "
        f"{SERVICE_DEFAULT_PATH}"
    )
    await ops_test.juju(*add_delay_cmd.split(), check=True)

    # reload the daemon for systemd to reflect changes
    reload_cmd = f"exec --unit {unit_name} -- sudo systemctl daemon-reload"
    await ops_test.juju(*reload_cmd.split(), check=True)


async def remove_restart_delay(ops_test: OpsTest, unit_name: str) -> None:
    """Removes the restart delay from the service."""
    remove_delay_cmd = (
        f"exec --unit {unit_name} -- sed -i -e '/^RestartSec=.*/d' {SERVICE_DEFAULT_PATH}"
    )
    await ops_test.juju(*remove_delay_cmd.split(), check=True)

    # reload the daemon for systemd to reflect changes
    reload_cmd = f"exec --unit {unit_name} -- sudo systemctl daemon-reload"
    await ops_test.juju(*reload_cmd.split(), check=True)


def is_up(ops_test: OpsTest, broker_id: int) -> bool:
    """Return if node up."""
    unit_name = ops_test.model.applications[APP_NAME].units[0].name
    kafka_zk_relation_data = get_kafka_zk_relation_data(
        unit_name=unit_name, model_full_name=ops_test.model_full_name
    )
    active_brokers = get_active_brokers(zookeeper_config=kafka_zk_relation_data)
    chroot = kafka_zk_relation_data.get("chroot", "")
    return f"{chroot}/brokers/ids/{broker_id}" in active_brokers


def assert_continuous_writes_consistency(
    result: ContinuousWritesResult,
    expected_lost_messages: int = 0,
    compare_lost_messages: bool = False,
):
    """Check results of a stopped ContinuousWrites call against expected results."""
    if compare_lost_messages:
        assert result.lost_messages >= expected_lost_messages
    else:
        assert (
            result.lost_messages == expected_lost_messages
        ), "Lost messages different from expected"
    assert (
        result.count + result.lost_messages - 1 == result.last_expected_message
    ), f"Last expected message {result.last_expected_message} doesn't match count {result.count} + lost_messages {result.lost_messages}"
