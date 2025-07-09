#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import re
import subprocess
import time
from dataclasses import dataclass
from subprocess import PIPE, CalledProcessError, check_output

import jubilant
from tenacity import RetryError, Retrying, stop_after_attempt, wait_fixed

from integration.ha.continuous_writes import ContinuousWritesResult
from integration.helpers import APP_NAME, CONTROLLER_NAME, KRaftMode
from integration.helpers.jubilant import KRaftUnitStatus, all_active_idle, kraft_quorum_status
from integration.helpers.pytest_operator import check_socket, get_unit_ipv4_address
from literals import KRAFT_NODE_ID_OFFSET, PATHS, SECURITY_PROTOCOL_PORTS

CONTROLLER_PORT = 9097
PROCESS = "kafka.Kafka"
SERVICE_DEFAULT_PATH = "/etc/systemd/system/snap.charmed-kafka.daemon.service"
RESTART_DELAY = 60
CLIENT_TIMEOUT = 30
REELECTION_TIME = 25
PRODUCING_MESSAGES = 10


logger = logging.getLogger(__name__)


@dataclass
class TopicDescription:
    leader: int
    in_sync_replicas: set


class ProcessError(Exception):
    """Raised when a process fails."""


class ProcessRunningError(Exception):
    """Raised when a process is running when it is not expected to be."""


def get_topic_description(juju: jubilant.Juju, topic: str) -> TopicDescription:
    """Get the broker with the topic leader.

    Args:
        juju (jubilant.Juju): Jubilant juju fixture.
        topic: the desired topic to check
    """
    bootstrap_servers = []
    for unit in juju.status().apps[APP_NAME].units:
        unit_ip = get_unit_ipv4_address(juju.model, unit)
        if not unit_ip:
            continue

        bootstrap_servers.append(
            f"{unit_ip}:{SECURITY_PROTOCOL_PORTS['SASL_PLAINTEXT', 'SCRAM-SHA-512'].client}"
        )

    output = ""
    for unit in juju.status().apps[APP_NAME].units:
        try:
            output = check_output(
                f"JUJU_MODEL={juju.model} juju ssh {unit} sudo -i 'charmed-kafka.topics --bootstrap-server {','.join(bootstrap_servers)} --command-config {PATHS['kafka']['CONF']}/client.properties --describe --topic {topic}'",
                stderr=PIPE,
                shell=True,
                universal_newlines=True,
            )
            break
        except CalledProcessError:
            logger.debug(f"Unit {unit} not available, trying next unit...")

    if not output:
        raise Exception("get_topic_description: No units available!")

    leader = int(re.search(r"Leader: (\d+)", output)[1])
    in_sync_replicas = {int(i) for i in re.search(r"Isr: ([\d,]+)", output)[1].split(",")}

    return TopicDescription(leader, in_sync_replicas)


def get_topic_offsets(juju: jubilant.Juju, topic: str) -> list[str]:
    """Get the offsets of a topic on a unit.

    Args:
        juju (jubilant.Juju): Jubilant juju fixture.
        topic: the desired topic to check
    """
    bootstrap_servers = []
    for unit in juju.status().apps[APP_NAME].units:
        unit_ip = get_unit_ipv4_address(juju.model, unit)
        if not unit_ip:
            continue

        bootstrap_servers.append(
            f"{unit_ip}:{SECURITY_PROTOCOL_PORTS['SASL_PLAINTEXT', 'SCRAM-SHA-512'].client}"
        )

    result = ""
    for unit in juju.status().apps[APP_NAME].units:
        try:
            # example of topic offset output: 'test-topic:0:10'
            result = check_output(
                f"JUJU_MODEL={juju.model} juju ssh {unit} sudo -i 'charmed-kafka.get-offsets --bootstrap-server {','.join(bootstrap_servers)} --command-config {PATHS['kafka']['CONF']}/client.properties --topic {topic}'",
                stderr=PIPE,
                shell=True,
                universal_newlines=True,
            )
            break
        except CalledProcessError:
            logger.debug(f"Unit {unit} not available, trying next unit...")

    if not result:
        raise Exception("get_topic_offsets: No units available!")

    return re.search(rf"{topic}:(\d+:\d+)", result)[1].split(":")


def send_control_signal(
    juju: jubilant.Juju, unit_name: str, signal: str, app_name: str = APP_NAME
) -> None:
    if len(juju.status().apps[app_name].units) < 3:
        juju.add_unit(app_name, num_units=1)
        juju.wait(lambda status: all_active_idle(status, app_name))

    machine_name = get_unit_machine_name(juju, unit_name)
    kill_cmd = f"lxc exec {machine_name} -- pkill --signal {signal} -f {PROCESS}"
    check_output(kill_cmd, shell=True, stderr=PIPE)


def patch_restart_delay(juju: jubilant.Juju, unit_name: str, delay: int) -> None:
    """Adds a restart delay in the DB service file.

    When the DB service fails it will now wait for `delay` number of seconds.
    """
    add_delay_cmd = f"sudo sed -i -e '/^[Service]/a RestartSec={delay}' " f"{SERVICE_DEFAULT_PATH}"
    juju.ssh(unit_name, add_delay_cmd)

    # reload the daemon for systemd to reflect changes
    reload_cmd = "sudo systemctl daemon-reload"
    juju.ssh(unit_name, reload_cmd)


def remove_restart_delay(juju: jubilant.Juju, unit_name: str) -> None:
    """Removes the restart delay from the service."""
    remove_delay_cmd = f"sudo sed -i -e '/^RestartSec=.*/d' {SERVICE_DEFAULT_PATH}"
    juju.ssh(unit_name, remove_delay_cmd)

    # reload the daemon for systemd to reflect changes
    reload_cmd = "sudo systemctl daemon-reload"
    juju.ssh(unit_name, reload_cmd)


def get_unit_machine_name(juju: jubilant.Juju, unit_name: str) -> str:
    """Gets current LXD machine name for a given unit name.

    Args:
        juju (jubilant.Juju): Jubilant juju fixture.
        unit_name: the Juju unit name to get from

    Returns:
        String of LXD machine name
            e.g juju-123456-0
    """
    raw_hostname = juju.ssh(unit_name, "hostname")
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
    limit_set_command = f"lxc config device set {machine_name} eth0 limits.priority=10"
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
    limit_set_command = f"lxc config device set {machine_name} eth0 limits.priority="
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


def reset_kafka_service(machine_name: str) -> None:
    """Restarts charmed-kafka daemon service on the target machine.

    Args:
        machine_name: lxc container hostname
    """
    # remove mask from eth0
    reset_command = f"lxc exec {machine_name} sudo snap restart charmed-kafka.daemon"
    subprocess.check_call(reset_command.split())


def assert_continuous_writes_consistency(result: ContinuousWritesResult):
    """Check results of a stopped ContinuousWrites call against expected results."""
    assert (
        result.count - 1 == result.last_expected_message
    ), f"Last expected message {result.last_expected_message} doesn't match count {result.count}"


def all_listeners_up(
    juju: jubilant.Juju, app_name: str, listener_port: int, timeout_seconds: int = 600
) -> None:
    """Waits until listeners on all units of the provided app `app_name` are up.

    Args:
        juju (jubilant.Juju): Jubilant juju fixture.
        app_name (str): Application name.
        listener_port (int): Listener port to check.
        timeout_seconds (int, optional): Wait timeout in seconds. Defaults to 600.
    """
    for _ in range(timeout_seconds // 30):
        all_up = True
        for unit in juju.status().apps[app_name].units:
            unit_ip = get_unit_ipv4_address(juju.model, unit)

            if not unit_ip:
                all_up = False
                continue

            if not check_socket(unit_ip, port=listener_port):
                logger.info(f"{unit} - {unit_ip}:{listener_port} not up yet...")
                all_up = False

        if all_up:
            return

        time.sleep(30)

    raise TimeoutError()


def assert_all_brokers_up(juju: jubilant.Juju, timeout_seconds: int = 600) -> None:
    """Waits until client listeners are up on all broker units."""
    return all_listeners_up(
        juju=juju,
        app_name=APP_NAME,
        listener_port=SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client,
        timeout_seconds=timeout_seconds,
    )


def assert_all_controllers_up(
    juju: jubilant.Juju, controller_app: str, timeout_seconds: int = 600
) -> None:
    """Waits until client listeners are up on all controller units."""
    return all_listeners_up(
        juju=juju,
        app_name=controller_app,
        listener_port=CONTROLLER_PORT,
        timeout_seconds=timeout_seconds,
    )


def assert_quorum_healthy(juju: jubilant.Juju, kraft_mode: KRaftMode):
    """Asserts KRaft Quorum is healthy, meaning all controller units are either LEADER or FOLLOWER, and all broker units are OBSERVERS.

    Args:
        juju (jubilant.Juju): Jubilant juju fixture.
        kraft_mode (KRaftMode): KRaft mode, either "single" or "multi".
    """
    logger.info("Asserting quorum is healthy...")
    app_name = CONTROLLER_NAME if kraft_mode == "multi" else APP_NAME
    address = get_unit_ipv4_address(juju.model, f"{app_name}/0")
    controller_port = CONTROLLER_PORT
    bootstrap_controller = f"{address}:{controller_port}"

    unit_status = kraft_quorum_status(juju, f"{app_name}/0", bootstrap_controller)

    offset = KRAFT_NODE_ID_OFFSET if kraft_mode == "single" else 0

    for unit_id, status in unit_status.items():
        if unit_id < offset + 100:
            assert status in (KRaftUnitStatus.FOLLOWER, KRaftUnitStatus.LEADER)
        else:
            assert status == KRaftUnitStatus.OBSERVER


def get_kraft_leader(juju: jubilant.Juju, unstable_unit: str | None = None) -> str:
    """Gets KRaft leader by querying metadata on one of the available controller units.

    Args:
        juju (jubilant.Juju): Jubilant juju fixture.
        unstable_unit (str | None, optional): The unit which is unstable (if any) and should be avoided to be used as bootstrap-controller. Defaults to None.

    Raises:
        Exception: If can not find the leader unit.

    Returns:
        str: The KRaft leader unit name.
    """
    status = {}
    for unit in juju.status().apps[CONTROLLER_NAME].units:
        if unit == unstable_unit:
            continue

        try:
            unit_ip = get_unit_ipv4_address(juju.model, unit)
            bootstrap_controller = f"{unit_ip}:{CONTROLLER_PORT}"
            status = kraft_quorum_status(
                juju, unit_name=unit, bootstrap_controller=bootstrap_controller
            )
            break
        except CalledProcessError:
            continue

    if not status:
        raise Exception("Can't find the KRaft leader.")

    for unit_id in status:
        if status[unit_id] == KRaftUnitStatus.LEADER:
            return f"{CONTROLLER_NAME}/{unit_id}"

    raise Exception("Can't find the KRaft leader.")


def get_kraft_quorum_lags(juju: jubilant.Juju) -> list[int]:
    """Gets KRaft units lags by querying metadata on one of the available controller units.

    Args:
        juju (jubilant.Juju): Jubilant juju fixture.

    Raises:
        Exception: If no controller unit is accessible or the metadata-quorum command fails.

    Returns:
        list[int]: list of lags on all brokers and controllers.
    """
    logger.info("Querying KRaft unit lags...")
    result = ""
    for unit in juju.status().apps[CONTROLLER_NAME].units:
        try:
            unit_ip = get_unit_ipv4_address(juju.model, unit)
            bootstrap_controller = f"{unit_ip}:{CONTROLLER_PORT}"
            result = check_output(
                f"JUJU_MODEL={juju.model} juju ssh {unit} sudo -i 'charmed-kafka.metadata-quorum  --command-config {PATHS['kafka']['CONF']}/server.properties --bootstrap-controller {bootstrap_controller} describe --replication'",
                stderr=PIPE,
                shell=True,
                universal_newlines=True,
            )
            break
        except CalledProcessError:
            continue

    if not result:
        raise Exception("Can't query KRaft quorum status.")

    # parse `kafka-metadata-quorum.sh` output
    # NodeId  DirectoryId  LogEndOffset  Lag  LastFetchTimestamp  LastCaughtUpTimestamp  Status
    lags = []
    for line in result.split("\n"):
        fields = [c.strip() for c in line.split("\t")]
        if len(fields) < 7 or fields[3] == "Lag":
            continue

        lags.append(int(fields[3]))

    logger.info(f"Lags: {lags}")
    return lags


def is_down(juju: jubilant.Juju, unit: str, port: int = CONTROLLER_PORT) -> bool:
    """Check if a unit's kafka process is down."""
    try:
        for attempt in Retrying(stop=stop_after_attempt(10), wait=wait_fixed(5)):
            with attempt:
                unit_ip = get_unit_ipv4_address(juju.model, unit)
                assert unit_ip
                assert not check_socket(unit_ip, port)
                logger.info(f"{unit_ip}:{port} is down")
    except RetryError:
        return False

    return True
