#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import re
import subprocess
from dataclasses import dataclass
from subprocess import PIPE, check_output
from typing import Optional

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


async def get_topic_description(
    ops_test: OpsTest, topic: str, unit_name: Optional[str] = None
) -> TopicDescription:
    """Get the broker with the topic leader.

    Args:
        ops_test: OpsTest utility class
        topic: the desired topic to check
        unit_name: unit to run the command on
    """
    bootstrap_servers = []
    for unit in ops_test.model.applications[APP_NAME].units:
        bootstrap_servers.append(
            await get_address(ops_test=ops_test, unit_num=unit.name.split("/")[-1])
            + f":{SECURITY_PROTOCOL_PORTS['SASL_PLAINTEXT'].client}"
        )
    unit_name = unit_name or ops_test.model.applications[APP_NAME].units[0].name

    output = check_output(
        f"JUJU_MODEL={ops_test.model_full_name} juju ssh {unit_name} sudo -i 'charmed-kafka.topics --bootstrap-server {','.join(bootstrap_servers)} --command-config {KafkaSnap.CONF_PATH}/client.properties --describe --topic {topic}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    leader = int(re.search(r"Leader: (\d+)", output)[1])
    in_sync_replicas = {int(i) for i in re.search(r"Isr: ([\d,]+)", output)[1].split(",")}

    return TopicDescription(leader, in_sync_replicas)


async def get_topic_offsets(
    ops_test: OpsTest, topic: str, unit_name: Optional[str] = None
) -> list[str]:
    """Get the offsets of a topic on a unit.

    Args:
        ops_test: OpsTest utility class
        topic: the desired topic to check
        unit_name: unit to run the command on
    """
    bootstrap_servers = []
    for unit in ops_test.model.applications[APP_NAME].units:
        bootstrap_servers.append(
            await get_address(ops_test=ops_test, unit_num=unit.name.split("/")[-1])
            + f":{SECURITY_PROTOCOL_PORTS['SASL_PLAINTEXT'].client}"
        )
    unit_name = unit_name or ops_test.model.applications[APP_NAME].units[0].name

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


async def get_unit_machine_name(ops_test: OpsTest, unit_name: str) -> str:
    """Gets current LXD machine name for a given unit name.

    Args:
        ops_test: OpsTest
        unit_name: the Juju unit name to get from

    Returns:
        String of LXD machine name
            e.g juju-123456-0
    """
    _, raw_hostname, _ = await ops_test.juju("ssh", unit_name, "hostname")
    return raw_hostname.strip()


def network_throttle(machine_name: str) -> None:
    """Cut network from a lxc container (without causing the change of the unit IP address).

    Args:
        machine_name: lxc container hostname
    """
    override_command = f"lxc config device override {machine_name} eth0"
    try:
        subprocess.check_call(override_command.split())
    except subprocess.CalledProcessError:
        # Ignore if the interface was already overridden.
        pass
    limit_set_command = f"lxc config device set {machine_name} eth0 limits.egress=0kbit"
    subprocess.check_call(limit_set_command.split())
    limit_set_command = f"lxc config device set {machine_name} eth0 limits.ingress=1kbit"
    subprocess.check_call(limit_set_command.split())
    limit_set_command = f"lxc config set {machine_name} limits.network.priority=10"
    subprocess.check_call(limit_set_command.split())


def network_release(machine_name: str) -> None:
    """Restore network from a lxc container (without causing the change of the unit IP address).

    Args:
        machine_name: lxc container hostname
    """
    limit_set_command = f"lxc config device set {machine_name} eth0 limits.egress="
    subprocess.check_call(limit_set_command.split())
    limit_set_command = f"lxc config device set {machine_name} eth0 limits.ingress="
    subprocess.check_call(limit_set_command.split())
    limit_set_command = f"lxc config set {machine_name} limits.network.priority="
    subprocess.check_call(limit_set_command.split())


def network_cut(machine_name: str) -> None:
    """Cut network from a lxc container.

    Args:
        machine_name: lxc container hostname
    """
    # apply a mask (device type `none`)
    cut_network_command = f"lxc config device add {machine_name} eth0 none"
    subprocess.check_call(cut_network_command.split())


def network_restore(machine_name: str) -> None:
    """Restore network from a lxc container.

    Args:
        machine_name: lxc container hostname
    """
    # remove mask from eth0
    restore_network_command = f"lxc config device remove {machine_name} eth0"
    subprocess.check_call(restore_network_command.split())


def is_up(ops_test: OpsTest, broker_id: int) -> bool:
    """Return if node up."""
    unit_name = ops_test.model.applications[APP_NAME].units[0].name
    kafka_zk_relation_data = get_kafka_zk_relation_data(
        unit_name=unit_name, model_full_name=ops_test.model_full_name
    )
    active_brokers = get_active_brokers(zookeeper_config=kafka_zk_relation_data)
    chroot = kafka_zk_relation_data.get("chroot", "")
    return f"{chroot}/brokers/ids/{broker_id}" in active_brokers


def assert_continuous_writes_consistency(result: ContinuousWritesResult):
    """Check results of a stopped ContinuousWrites call against expected results."""
    assert (
        result.count + result.lost_messages - 1 == result.last_expected_message
    ), f"Last expected message {result.last_expected_message} doesn't match count {result.count} + lost_messages {result.lost_messages}"
