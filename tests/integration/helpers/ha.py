#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import logging
import re
import subprocess
from dataclasses import dataclass
from subprocess import PIPE, CalledProcessError, check_output

from pytest_operator.plugin import OpsTest
from tenacity import RetryError, Retrying, stop_after_attempt, wait_fixed

from integration.ha.continuous_writes import ContinuousWritesResult
from integration.helpers.pytest_operator import (
    APP_NAME,
    CONTROLLER_NAME,
    KRaftMode,
    KRaftUnitStatus,
    check_socket,
    get_address,
    get_unit_ipv4_address,
    kraft_quorum_status,
)
from literals import KRAFT_NODE_ID_OFFSET, PATHS, SECURITY_PROTOCOL_PORTS

CONTROLLER_PORT = 9097
PROCESS = "kafka.Kafka"
SERVICE_DEFAULT_PATH = "/etc/systemd/system/snap.charmed-kafka.daemon.service"
ZK = "zookeeper"
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
            + f":{SECURITY_PROTOCOL_PORTS['SASL_PLAINTEXT', 'SCRAM-SHA-512'].client}"
        )

    output = ""
    for unit in ops_test.model.applications[APP_NAME].units:
        try:
            output = check_output(
                f"JUJU_MODEL={ops_test.model_full_name} juju ssh {unit.name} sudo -i 'charmed-kafka.topics --bootstrap-server {','.join(bootstrap_servers)} --command-config {PATHS['kafka']['CONF']}/client.properties --describe --topic {topic}'",
                stderr=PIPE,
                shell=True,
                universal_newlines=True,
            )
            break
        except CalledProcessError:
            logger.debug(f"Unit {unit.name} not available, trying next unit...")

    if not output:
        raise Exception("get_topic_description: No units available!")

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
            + f":{SECURITY_PROTOCOL_PORTS['SASL_PLAINTEXT', 'SCRAM-SHA-512'].client}"
        )

    result = ""
    for unit in ops_test.model.applications[APP_NAME].units:
        try:
            # example of topic offset output: 'test-topic:0:10'
            result = check_output(
                f"JUJU_MODEL={ops_test.model_full_name} juju ssh {unit.name} sudo -i 'charmed-kafka.get-offsets --bootstrap-server {','.join(bootstrap_servers)} --command-config {PATHS['kafka']['CONF']}/client.properties --topic {topic}'",
                stderr=PIPE,
                shell=True,
                universal_newlines=True,
            )
            break
        except CalledProcessError:
            logger.debug(f"Unit {unit.name} not available, trying next unit...")

    if not result:
        raise Exception("get_topic_offsets: No units available!")

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


async def all_listeners_up(
    ops_test: OpsTest, app_name: str, listener_port: int, timeout_seconds: int = 600
):
    """Waits until listeners on all units of the provided app `app_name` are up.

    Args:
        ops_test (OpsTest): OpsTest fixture.
        app_name (str): Application name.
        listener_port (int): Listener port to check.
        timeout_seconds (int, optional): Wait timeout in seconds. Defaults to 600.
    """
    async with ops_test.fast_forward(fast_interval="30s"):
        for _ in range(timeout_seconds // 30):
            all_up = True
            for unit in ops_test.model.applications[app_name].units:
                unit_ip = get_unit_ipv4_address(ops_test.model_full_name, unit.name)

                if not unit_ip:
                    all_up = False
                    continue

                if not check_socket(unit_ip, port=listener_port):
                    logger.info(f"{unit.name} - {unit_ip}:{listener_port} not up yet...")
                    all_up = False

            if all_up:
                return

            await asyncio.sleep(30)

    raise TimeoutError()


async def all_brokers_up(ops_test: OpsTest, timeout_seconds: int = 600):
    """Waits until client listeners are up on all broker units."""
    await all_listeners_up(
        ops_test=ops_test,
        app_name=APP_NAME,
        listener_port=SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client,
        timeout_seconds=timeout_seconds,
    )


async def all_controllers_up(ops_test: OpsTest, controller_app: str, timeout_seconds: int = 600):
    """Waits until client listeners are up on all controller units."""
    await all_listeners_up(
        ops_test=ops_test,
        app_name=controller_app,
        listener_port=CONTROLLER_PORT,
        timeout_seconds=timeout_seconds,
    )


async def assert_quorum_healthy(ops_test: OpsTest, kraft_mode: KRaftMode):
    """Asserts KRaft Quorum is healthy, meaning all controller units are either LEADER or FOLLOWER, and all broker units are OBSERVERS.

    Args:
        ops_test (OpsTest): OpsTest fixture.
        kraft_mode (KRaftMode): KRaft mode, either "single" or "multi".
    """
    logger.info("Asserting quorum is healthy...")
    app_name = CONTROLLER_NAME if kraft_mode == "multi" else APP_NAME
    address = await get_address(ops_test=ops_test, app_name=app_name)
    controller_port = CONTROLLER_PORT
    bootstrap_controller = f"{address}:{controller_port}"

    unit_status = kraft_quorum_status(ops_test, f"{app_name}/0", bootstrap_controller)

    offset = KRAFT_NODE_ID_OFFSET if kraft_mode == "single" else 0

    for unit_id, status in unit_status.items():
        if unit_id < offset + 100:
            assert status in (KRaftUnitStatus.FOLLOWER, KRaftUnitStatus.LEADER)
        else:
            assert status == KRaftUnitStatus.OBSERVER


async def get_kraft_leader(ops_test: OpsTest, unstable_unit: str | None = None) -> str:
    """Gets KRaft leader by querying metadata on one of the available controller units.

    Args:
        ops_test (OpsTest): OpsTest fixture.
        unstable_unit (str | None, optional): The unit which is unstable (if any) and should be avoided to be used as bootstrap-controller. Defaults to None.

    Raises:
        Exception: If can not find the leader unit.

    Returns:
        str: The KRaft leader unit name.
    """
    status = {}
    for unit in ops_test.model.applications[CONTROLLER_NAME].units:
        if unit.name == unstable_unit:
            continue

        try:
            unit_ip = get_unit_ipv4_address(ops_test.model_full_name, unit.name)
            bootstrap_controller = f"{unit_ip}:{CONTROLLER_PORT}"
            status = kraft_quorum_status(
                ops_test, unit_name=unit.name, bootstrap_controller=bootstrap_controller
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


def get_kraft_quorum_lags(ops_test: OpsTest) -> list[int]:
    """Gets KRaft units lags by querying metadata on one of the available controller units.

    Args:
        ops_test (OpsTest): OpsTest fixture.

    Raises:
        Exception: If no controller unit is accessible or the metadata-quorum command fails.

    Returns:
        list[int]: list of lags on all brokers and controllers.
    """
    logger.info("Querying KRaft unit lags...")
    result = ""
    for unit in ops_test.model.applications[CONTROLLER_NAME].units:
        try:
            unit_ip = get_unit_ipv4_address(ops_test.model_full_name, unit.name)
            bootstrap_controller = f"{unit_ip}:{CONTROLLER_PORT}"
            result = check_output(
                f"JUJU_MODEL={ops_test.model_full_name} juju ssh {unit.name} sudo -i 'charmed-kafka.metadata-quorum  --command-config {PATHS['kafka']['CONF']}/server.properties --bootstrap-controller {bootstrap_controller} describe --replication'",
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


async def is_down(ops_test: OpsTest, unit: str) -> bool:
    """Check if a unit's kafka process is down."""
    try:
        for attempt in Retrying(stop=stop_after_attempt(10), wait=wait_fixed(5)):
            with attempt:
                search_db_process = f"exec --unit {unit} pgrep -x java"
                _, processes, _ = await ops_test.juju(*search_db_process.split())
                # splitting processes by "\n" results in one or more empty lines, hence we
                # need to process these lines accordingly.
                processes = [proc for proc in processes.split("\n") if proc]
                if len(processes) > 0:
                    raise ProcessRunningError
    except RetryError:
        return False

    return True
