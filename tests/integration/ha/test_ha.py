#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time

import jubilant
import pytest
from flaky import flaky

from integration.ha.continuous_writes import ContinuousWrites
from integration.helpers import (
    APP_NAME,
    CONTROLLER_NAME,
    DUMMY_NAME,
    REL_NAME_ADMIN,
    TEST_DEFAULT_MESSAGES,
    broker_id_to_unit_id,
)
from integration.helpers.ha import (
    CLIENT_TIMEOUT,
    PRODUCING_MESSAGES,
    REELECTION_TIME,
    RESTART_DELAY,
    assert_all_brokers_up,
    assert_continuous_writes_consistency,
    get_topic_description,
    get_topic_offsets,
    get_unit_machine_name,
    is_down,
    network_cut,
    network_release,
    network_restore,
    network_throttle,
    send_control_signal,
)
from integration.helpers.jubilant import (
    BASE,
    all_active_idle,
    check_logs,
    deploy_cluster,
    get_unit_ipv4_address,
    kraft_quorum_status,
    produce_and_check_logs,
)
from literals import SECURITY_PROTOCOL_PORTS

logger = logging.getLogger(__name__)

BROKER_PORT = SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client


def test_build_and_deploy(juju: jubilant.Juju, kafka_charm, app_charm, kraft_mode, kafka_apps):
    deploy_cluster(
        juju=juju,
        charm=kafka_charm,
        kraft_mode=kraft_mode,
    )
    juju.deploy(app_charm, app=DUMMY_NAME, num_units=1, base=BASE)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=3600,
    )

    juju.integrate(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=20,
        timeout=1200,
    )

    status = juju.status()
    assert status.apps[APP_NAME].app_status.current == "active"
    assert status.apps[DUMMY_NAME].app_status.current == "active"


def test_replicated_events(juju: jubilant.Juju, kafka_apps):
    juju.add_unit(APP_NAME, num_units=2)
    juju.wait(
        lambda status: all_active_idle(status, APP_NAME),
        delay=3,
        successes=40,
        timeout=1800,
    )

    logger.info("Producing messages and checking on all units")
    produce_and_check_logs(
        juju=juju,
        kafka_unit_name=f"{APP_NAME}/0",
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="replicated-topic",
        replication_factor=3,
        num_partitions=1,
    )
    topic_description = get_topic_description(juju, "replicated-topic")

    assert topic_description.in_sync_replicas == {100, 101, 102}
    # check offsets in the two remaining units
    assert get_topic_offsets(juju=juju, topic="replicated-topic") == [
        "0",
        str(TEST_DEFAULT_MESSAGES),
    ]


def test_multi_cluster_isolation(juju: jubilant.Juju, kafka_charm):
    second_kafka_name = f"{APP_NAME}-two"
    second_controller_name = f"{CONTROLLER_NAME}-two"

    deploy_cluster(
        juju=juju,
        charm=kafka_charm,
        kraft_mode="multi",
        app_name_broker=second_kafka_name,
        app_name_controller=second_controller_name,
    )

    produce_and_check_logs(
        juju=juju,
        kafka_unit_name=f"{APP_NAME}/0",
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="hot-topic",
        replication_factor=3,
        num_partitions=1,
    )

    # Check that logs are not found on the second cluster
    with pytest.raises(AssertionError):
        check_logs(
            juju=juju,
            kafka_unit_name=f"{second_kafka_name}/0",
            topic="hot-topic",
        )

    juju.remove_application(second_kafka_name, destroy_storage=True, force=True)
    juju.remove_application(second_controller_name, destroy_storage=True, force=True)


@flaky(max_runs=3, min_passes=1)
def test_kill_broker_with_topic_leader(
    juju: jubilant.Juju,
    restore_state,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
    restart_delay,
):
    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    initial_leader_num = topic_description.leader

    logger.info(
        f"Killing broker of leader for topic '{ContinuousWrites.TOPIC_NAME}': {initial_leader_num}"
    )
    send_control_signal(
        juju=juju,
        unit_name=f"{APP_NAME}/{broker_id_to_unit_id(initial_leader_num)}",
        signal="SIGKILL",
    )

    # Give time for the remaining units to notice leader going down
    time.sleep(REELECTION_TIME)

    # Check offsets after killing leader
    initial_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)

    # verify replica is not in sync and check that leader changed
    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    assert initial_leader_num != topic_description.leader
    assert topic_description.in_sync_replicas == {100, 101, 102} - {initial_leader_num}

    # Give time for the service to restart
    time.sleep(RESTART_DELAY * 2)

    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    next_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)

    assert topic_description.in_sync_replicas == {100, 101, 102}
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)


@flaky(max_runs=3, min_passes=1)
def test_restart_broker_with_topic_leader(
    juju: jubilant.Juju,
    restore_state,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    leader_num = topic_description.leader

    logger.info(
        f"Restarting broker of leader for topic '{ContinuousWrites.TOPIC_NAME}': {leader_num}"
    )
    send_control_signal(
        juju=juju,
        unit_name=f"{APP_NAME}/{broker_id_to_unit_id(leader_num)}",
        signal="SIGTERM",
    )
    # Give time for the service to restart
    time.sleep(REELECTION_TIME * 2)

    initial_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    time.sleep(CLIENT_TIMEOUT)
    next_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)

    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    assert topic_description.in_sync_replicas == {100, 101, 102}
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)


@flaky(max_runs=3, min_passes=1)
def test_freeze_broker_with_topic_leader(
    juju: jubilant.Juju,
    restore_state,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
    controller_app: str,
    kraft_mode,
):
    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    initial_leader_num = topic_description.leader

    controller_unit_num = (
        next(iter({0, 1, 2} - {broker_id_to_unit_id(initial_leader_num)}))
        if kraft_mode == "single"
        else 0
    )
    address = get_unit_ipv4_address(juju.model, f"{controller_app}/{controller_unit_num}")
    controller_port = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].controller
    bootstrap_controller = f"{address}:{controller_port}"
    controller_unit = f"{controller_app}/{controller_unit_num}"

    logger.info(
        f"Freezing broker of leader for topic '{ContinuousWrites.TOPIC_NAME}': {initial_leader_num}"
    )
    send_control_signal(
        juju=juju,
        unit_name=f"{APP_NAME}/{broker_id_to_unit_id(initial_leader_num)}",
        signal="SIGSTOP",
    )
    time.sleep(REELECTION_TIME * 2)

    # verify replica is not in sync
    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    assert topic_description.in_sync_replicas == {100, 101, 102} - {initial_leader_num}
    assert initial_leader_num != topic_description.leader

    # verify the broker left the cluster
    # this could only be done in multi mode since in single mode, the controller is registered as FOLLOWER.
    if kraft_mode == "multi":
        while initial_leader_num in kraft_quorum_status(
            juju, controller_unit, bootstrap_controller
        ):
            logging.info(f"Broker {initial_leader_num} reported as up")
            time.sleep(REELECTION_TIME)

    # verify new writes are continuing. Also, check that leader changed
    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    initial_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    time.sleep(CLIENT_TIMEOUT * 2)
    next_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)

    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    # Un-freeze the process
    logger.info(f"Un-freezing broker: {initial_leader_num}")
    send_control_signal(
        juju=juju,
        unit_name=f"{APP_NAME}/{broker_id_to_unit_id(initial_leader_num)}",
        signal="SIGCONT",
    )
    time.sleep(REELECTION_TIME)
    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)

    # verify the unit is now rejoined the cluster
    assert initial_leader_num in kraft_quorum_status(
        juju, controller_unit, bootstrap_controller
    ), f"Broker {initial_leader_num} reported as down"
    assert topic_description.in_sync_replicas == {100, 101, 102}

    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)


@flaky(max_runs=3, min_passes=1)
def test_full_cluster_crash(
    juju: jubilant.Juju,
    restore_state,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
    restart_delay,
):
    # Let some time pass for messages to be produced
    time.sleep(PRODUCING_MESSAGES)

    logger.info("Killing all brokers...")
    # kill all units "simultaneously"
    units = juju.status().apps[APP_NAME].units
    for unit in units:
        send_control_signal(juju, unit, signal="SIGKILL")

    # Check that all servers are down at the same time
    for unit in units:
        assert is_down(juju, unit, port=BROKER_PORT)

    # Give time for the service to restart
    time.sleep(RESTART_DELAY * 2)

    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    initial_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    time.sleep(CLIENT_TIMEOUT * 2)
    next_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)

    assert int(next_offsets[-1]) > int(initial_offsets[-1])
    assert topic_description.in_sync_replicas == {100, 101, 102}

    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)


@flaky(max_runs=3, min_passes=1)
def test_full_cluster_restart(
    juju: jubilant.Juju,
    restore_state,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    # Let some time pass for messages to be produced
    time.sleep(PRODUCING_MESSAGES)

    logger.info("Restarting all brokers...")
    # Restart all units "simultaneously"
    units = juju.status().apps[APP_NAME].units
    for unit in units:
        send_control_signal(juju, unit, signal="SIGTERM")

    # Give time for the service to restart
    time.sleep(REELECTION_TIME * 2)

    initial_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    time.sleep(CLIENT_TIMEOUT * 2)
    next_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)

    assert int(next_offsets[-1]) > int(initial_offsets[-1])
    assert topic_description.in_sync_replicas == {100, 101, 102}

    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)


@flaky(max_runs=3, min_passes=1)
def test_network_cut_without_ip_change(
    juju: jubilant.Juju,
    restore_state,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    # Let some time pass for messages to be produced
    time.sleep(PRODUCING_MESSAGES)

    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    initial_leader_num = topic_description.leader
    leader_unit_name = f"{APP_NAME}/{broker_id_to_unit_id(initial_leader_num)}"
    leader_machine_name = get_unit_machine_name(juju=juju, unit_name=leader_unit_name)

    logger.info(
        f"Throttling network for leader of topic '{ContinuousWrites.TOPIC_NAME}': {initial_leader_num}"
    )
    network_throttle(machine_name=leader_machine_name)
    time.sleep(REELECTION_TIME * 2)

    # verify replica is not in sync
    topic_description = get_topic_description(
        juju=juju,
        topic=ContinuousWrites.TOPIC_NAME,
    )
    assert topic_description.in_sync_replicas == {100, 101, 102} - {initial_leader_num}
    assert initial_leader_num != topic_description.leader

    # verify new writes are continuing. Also, check that leader changed
    topic_description = get_topic_description(
        juju=juju,
        topic=ContinuousWrites.TOPIC_NAME,
    )
    initial_offsets = get_topic_offsets(
        juju=juju,
        topic=ContinuousWrites.TOPIC_NAME,
    )
    time.sleep(CLIENT_TIMEOUT * 2)
    next_offsets = get_topic_offsets(
        juju=juju,
        topic=ContinuousWrites.TOPIC_NAME,
    )

    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    # Release the network
    logger.info(f"Releasing network of broker: {initial_leader_num}")
    network_release(machine_name=leader_machine_name)
    time.sleep(REELECTION_TIME)

    assert_all_brokers_up(juju)
    result = c_writes.stop()

    # verify the unit's now rejoined the cluster, retry for a couple of times to avoid flakiness
    for _ in range(6):
        topic_description = get_topic_description(
            juju=juju,
            topic=ContinuousWrites.TOPIC_NAME,
        )
        if topic_description.in_sync_replicas == {100, 101, 102}:
            break

        time.sleep(30)

    assert topic_description.in_sync_replicas == {100, 101, 102}
    assert_continuous_writes_consistency(result=result)


# TODO: enable after IP change handling of the charm is fixed.
@pytest.mark.skip(reason="IP change is not handled gracefully, leading to unpredictable results")
def test_network_cut(
    juju: jubilant.Juju,
    restore_state,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    # Let some time pass for messages to be produced
    time.sleep(PRODUCING_MESSAGES)

    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    initial_leader_num = topic_description.leader
    leader_unit_name = f"{APP_NAME}/{broker_id_to_unit_id(initial_leader_num)}"
    leader_machine_name = get_unit_machine_name(juju=juju, unit_name=leader_unit_name)

    logger.info(
        f"Cutting network for leader of topic '{ContinuousWrites.TOPIC_NAME}': {initial_leader_num}"
    )
    network_cut(machine_name=leader_machine_name)
    time.sleep(REELECTION_TIME * 2)

    # verify replica is not in sync, check on one of the remaining units
    topic_description = get_topic_description(
        juju=juju,
        topic=ContinuousWrites.TOPIC_NAME,
    )
    assert topic_description.in_sync_replicas == {100, 101, 102} - {initial_leader_num}
    assert initial_leader_num != topic_description.leader

    # verify new writes are continuing. Also, check that leader changed
    topic_description = get_topic_description(
        juju=juju,
        topic=ContinuousWrites.TOPIC_NAME,
    )
    initial_offsets = get_topic_offsets(
        juju=juju,
        topic=ContinuousWrites.TOPIC_NAME,
    )
    time.sleep(CLIENT_TIMEOUT * 2)
    next_offsets = get_topic_offsets(
        juju=juju,
        topic=ContinuousWrites.TOPIC_NAME,
    )

    assert int(next_offsets[-1]) > int(initial_offsets[-1]), "Messages not increasing"

    # Release the network
    logger.info(f"Restoring network of broker: {initial_leader_num}")
    network_restore(machine_name=leader_machine_name)

    assert_all_brokers_up(juju)
    result = c_writes.stop()

    # verify the unit's now rejoined the cluster, retry for a couple of times to avoid flakiness
    for _ in range(6):
        topic_description = get_topic_description(
            juju=juju,
            topic=ContinuousWrites.TOPIC_NAME,
        )
        if topic_description.in_sync_replicas == {100, 101, 102}:
            break

        time.sleep(30)

    assert topic_description.in_sync_replicas == {100, 101, 102}
    assert_continuous_writes_consistency(result=result)
