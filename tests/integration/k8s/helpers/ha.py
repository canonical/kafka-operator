#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import re
import string
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from subprocess import PIPE, CalledProcessError, check_call, check_output
from typing import Literal

import jubilant
from single_kernel_kafka.core.literals import (
    BROKER,
    CONTAINER,
    KRAFT_NODE_ID_OFFSET,
    PATHS,
    SECURITY_PROTOCOL_PORTS,
)
from tenacity import RetryError, Retrying, retry, retry_if_result, stop_after_attempt, wait_fixed

from integration.k8s.ha.continuous_writes import ContinuousWritesResult
from integration.k8s.helpers import (
    APP_NAME,
    CONTROLLER_NAME,
    KRaftMode,
    KRaftUnitStatus,
    check_socket,
    get_bootstrap_servers,
    get_k8s_host_from_unit,
    get_unit_address_map,
)
from integration.k8s.helpers.jubilant import get_unit_ipv4_address, kraft_quorum_status

PROCESS = "kafka.Kafka"
SERVICE = "kafka"
BROKER_PORT = SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client
CONTROLLER_PORT = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].controller


logger = logging.getLogger(__name__)


@dataclass
class TopicDescription:
    leader: int
    in_sync_replicas: set


class ProcessError(Exception):
    """Raised when a process fails."""


class ProcessRunningError(Exception):
    """Raised when a process is running when it is not expected to be."""


def get_topic_description(
    juju: jubilant.Juju,
    topic: str,
) -> TopicDescription:
    """Get the broker with the topic leader.

    Args:
        juju: jubilant.Juju fixture
        topic: the desired topic to check
    """
    bootstrap_servers = get_bootstrap_servers(f"{juju.model}")

    output = ""
    for unit in juju.status().apps[APP_NAME].units:
        try:
            output = check_output(
                f"kubectl exec {unit.replace('/', '-')} -c {CONTAINER} -n {juju.model} -- {BROKER.paths['BIN']}/bin/kafka-topics.sh --describe --topic {topic} --bootstrap-server {bootstrap_servers} --command-config {BROKER.paths['CONF']}/client.properties",
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
        juju: jubilant.Juju fixture
        topic: the desired topic to check
        unit_name: unit to run the command on
    """
    bootstrap_servers = get_bootstrap_servers(f"{juju.model}")

    result = ""
    for unit in juju.status().apps[APP_NAME].units:
        try:
            # example of topic offset output: 'test-topic:0:10'
            result = check_output(
                f"kubectl exec {unit.replace('/', '-')} -c {CONTAINER} -n {juju.model} -- {BROKER.paths['BIN']}/bin/kafka-get-offsets.sh --topic {topic} --bootstrap-server {bootstrap_servers} --command-config {BROKER.paths['CONF']}/client.properties",
                stderr=PIPE,
                shell=True,
                universal_newlines=True,
            )
        except CalledProcessError:
            logger.debug(f"Unit {unit} not available, trying next unit...")

    if not result:
        raise Exception("get_topic_offsets: No units available!")

    return re.search(rf"{topic}:(\d+:\d+)", result)[1].split(":")


def send_control_signal(
    juju: jubilant.Juju,
    unit_name: str,
    signal: str,
    container_name: str = CONTAINER,
) -> None:
    f"""Issues given job control signals to a Kafka process on a given Juju unit.

    Args:
        juju: jubilant.Juju fixture
        unit_name: the Juju unit name
        signal: the signal to issue
            e.g `SIGKILL`, `SIGSTOP`, `SIGCONT` etc
        container_name: the container to run command on
            Defaults to '{container_name}'
    """
    cmd = f"kubectl exec {unit_name.replace('/', '-')} -c {container_name} -n {juju.model} -- pkill --signal {signal} -f {PROCESS}"
    check_output(
        cmd,
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )


def modify_pebble_restart_delay(
    juju: jubilant.Juju,
    policy: Literal["extend", "restore"],
    app_name: str = APP_NAME,
    container_name: str = CONTAINER,
    service_name: str = BROKER.service,
) -> None:
    f"""Modify the pebble restart delay of the underlying process.

    Args:
        juju: jubilant.Juju fixture
        policy: the pebble restart delay policy to apply
            Either 'extend' or 'restore'
        app_name: the Kafka Juju application
        container_name: the container to run command on
            Defaults to '{container_name}'
        service_name: the service running in the container
            Defaults to '{service_name}'
    """
    now = datetime.now().isoformat()
    pebble_patch_path = f"/tmp/pebble_plan_{now}.yaml"

    for unit in juju.status().apps[app_name].units:
        logger.info(
            f"Copying extend_pebble_restart_delay manifest to {unit} {container_name} container..."
        )
        check_output(
            f"kubectl cp ./tests/integration/ha/manifests/{policy}_pebble_restart_delay.yaml {unit.replace('/', '-')}:{pebble_patch_path} -c {container_name} -n {juju.model}",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )

        logger.info(f"Adding {policy} policy to {container_name} pebble plan...")
        check_output(
            f"kubectl exec {unit.replace('/', '-')} -c {container_name} -n {juju.model} -- /charm/bin/pebble add --combine {service_name}-{uuid.uuid4().hex} {pebble_patch_path}",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )

        logger.info(f"Replanning {service_name} service...")
        check_output(
            f"kubectl exec {unit.replace('/', '-')} -c {container_name} -n {juju.model} -- /charm/bin/pebble restart kafka",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )


def deploy_chaos_mesh(namespace: str) -> None:
    """Deploy chaos mesh to the provided namespace.

    Args:
        namespace: The namespace to deploy chaos mesh to
    """
    env = os.environ
    env["KUBECONFIG"] = os.path.expanduser("~/.kube/config")

    check_output(
        " ".join(
            [
                "sudo",
                "tests/integration/ha/scripts/deploy_chaos_mesh.sh",
                namespace,
            ]
        ),
        shell=True,
        env=env,
    )


def destroy_chaos_mesh(namespace: str) -> None:
    """Remove chaos mesh from the provided namespace.

    Args:
        namespace: The namespace to deploy chaos mesh to
    """
    env = os.environ
    env["KUBECONFIG"] = os.path.expanduser("~/.kube/config")

    check_output(
        f"sudo tests/integration/ha/scripts/destroy_chaos_mesh.sh {namespace}",
        shell=True,
        env=env,
    )


def isolate_instance_from_cluster(juju: jubilant.Juju, unit_name: str) -> None:
    """Apply a NetworkChaos file to use chaos-mesh to simulate a network cut.

    Args:
        juju: jubilant.Juju fixture
        unit_name: the Juju unit running the process
    """
    with tempfile.NamedTemporaryFile() as temp_file:
        with open(
            "tests/integration/ha/manifests/chaos_network_loss.yaml", "r"
        ) as chaos_network_loss_file:
            template = string.Template(chaos_network_loss_file.read())
            chaos_network_loss = template.substitute(
                namespace=juju.model,
                pod=unit_name.replace("/", "-"),
            )

            temp_file.write(str.encode(chaos_network_loss))
            temp_file.flush()

        env = os.environ
        env["KUBECONFIG"] = os.path.expanduser("~/.kube/config")

        check_output(" ".join(["kubectl", "apply", "-f", temp_file.name]), shell=True, env=env)


def remove_instance_isolation(juju: jubilant.Juju) -> None:
    """Delete the NetworkChaos that is isolating the primary unit of the cluster.

    Args:
        juju: jubilant.Juju fixture
    """
    env = os.environ
    env["KUBECONFIG"] = os.path.expanduser("~/.kube/config")

    check_output(
        f"kubectl -n {juju.model} delete --ignore-not-found=true networkchaos network-loss-primary",
        shell=True,
        env=env,
    )


def add_k8s_hosts(juju: jubilant.Juju):
    """Adds a the pod dns hostnames to the local /etc/hosts file."""
    address_map = get_unit_address_map(model=f"{juju.model}")
    dns_pod_map = [
        f"{pod_ip} {get_k8s_host_from_unit(unit_name)}"
        for unit_name, pod_ip in address_map.items()
    ]

    for item in dns_pod_map:
        cmd = f"echo {item} | sudo tee -a /etc/hosts"
        check_output(cmd, stderr=PIPE, shell=True, universal_newlines=True)
        logger.info(f"Added {item} to /etc/hosts")


def remove_k8s_hosts(juju: jubilant.Juju):
    """Removes the dns hostnames from /etc/hosts file."""
    address_map = get_unit_address_map(model=f"{juju.model}")

    for unit_name in address_map.keys():
        cmd = f"sudo sed -i -e '/.*{get_k8s_host_from_unit(unit_name)}$/d' /etc/hosts"
        check_output(cmd, stderr=PIPE, shell=True, universal_newlines=True)
        logger.info(f"Removed {unit_name} from /etc/hosts")


def delete_pod(juju: jubilant.Juju, unit_name: str):
    check_output(
        f"kubectl delete pod {unit_name.replace('/', '-')} -n {juju.model}",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )


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


def assert_all_brokers_up(
    juju: jubilant.Juju, timeout_seconds: int = 600, port: int = BROKER_PORT
) -> None:
    """Waits until client listeners are up on all broker units."""
    return all_listeners_up(
        juju=juju,
        app_name=APP_NAME,
        listener_port=port,
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
                f"JUJU_MODEL={juju.model} juju ssh --container {CONTAINER} {unit} '{BROKER.paths['BIN']}/bin/kafka-metadata-quorum.sh --command-config {PATHS['kafka']['CONF']}/kraft-client.properties --bootstrap-controller {bootstrap_controller} describe --replication'",
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


@retry(
    wait=wait_fixed(20),
    stop=stop_after_attempt(15),
    retry=retry_if_result(lambda result: result is False),
    retry_error_callback=lambda _: False,
)
def assert_quorum_lag_is_zero(juju: jubilant.Juju):
    return not any(get_kraft_quorum_lags(juju))


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


def reset_kafka_service(model: str, unit_name: str) -> None:
    """Restarts kafka pebble service on the target uni.

    Args:
        model: Juju model name
        unit_name: Juju unit name
    """
    pod_name = unit_name.replace("/", "-")
    reset_command = f"kubectl exec -n {model} -c kafka {pod_name} -- pebble restart kafka"
    logger.info(f"Running {reset_command}")
    check_call(reset_command.split())
