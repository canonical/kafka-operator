#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import time

import flaky
import jubilant
import pytest

from integration.k8s.ha.continuous_writes import ContinuousWrites
from integration.k8s.helpers import (
    APP_NAME,
    CONTROLLER_NAME,
    DUMMY_NAME,
    REL_NAME_ADMIN,
    broker_id_to_unit_id,
)
from integration.k8s.helpers.ha import (
    add_k8s_hosts,
    assert_continuous_writes_consistency,
    delete_pod,
    get_topic_description,
    get_topic_offsets,
    isolate_instance_from_cluster,
    remove_instance_isolation,
    remove_k8s_hosts,
    send_control_signal,
)
from integration.k8s.helpers.jubilant import all_active_idle, check_logs, deploy_cluster

RESTART_DELAY = 60
CLIENT_TIMEOUT = 30
REELECTION_TIME = 25

logger = logging.getLogger(__name__)


@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
def test_build_and_deploy(juju: jubilant.Juju, kafka_charm, app_charm, kraft_mode, kafka_apps):
    deploy_cluster(
        juju=juju,
        charm=kafka_charm,
        kraft_mode=kraft_mode,
        config_broker={"expose-external": "nodeport"},
    )
    juju.deploy(app_charm, app=DUMMY_NAME, trust=True)

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
        timeout=2000,
    )

    status = juju.status()
    assert status.apps[APP_NAME].app_status.current == "active"
    assert status.apps[DUMMY_NAME].app_status.current == "active"


# run this test early, in case of resource limits on runners with too many units
def test_multi_cluster_isolation(juju: jubilant.Juju, kafka_charm, kafka_apps):
    second_kafka_name = f"{APP_NAME}-two"
    second_controller_name = f"{CONTROLLER_NAME}-two"

    deploy_cluster(
        juju=juju,
        charm=kafka_charm,
        kraft_mode="multi",
        app_name_broker=second_kafka_name,
        app_name_controller=second_controller_name,
    )

    status = juju.status()
    assert status.apps[second_kafka_name].app_status.current == "active"
    assert status.apps[second_controller_name].app_status.current == "active"

    # produce to first cluster
    juju.run(f"{DUMMY_NAME}/0", "produce")
    time.sleep(10)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=1000,
    )

    # logs exist on first cluster
    check_logs(
        juju=juju,
        kafka_unit_name=f"{APP_NAME}/0",
        topic="test-topic",
    )

    # Check that logs are not found on the second cluster
    with pytest.raises(AssertionError):
        check_logs(
            juju=juju,
            kafka_unit_name=f"{second_kafka_name}/0",
            topic="test-topic",
        )

    # fast removal of second cluster
    juju.remove_application(second_kafka_name, destroy_storage=True, force=True)
    juju.remove_application(second_controller_name, destroy_storage=True, force=True)


def test_scale_up_controller_kafka(juju: jubilant.Juju, kraft_mode, kafka_apps):
    juju.add_unit(APP_NAME, num_units=2)
    if kraft_mode == "multi":
        juju.add_unit(CONTROLLER_NAME, num_units=2)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=3,
        successes=10,
        timeout=1200,
    )


@flaky.flaky(max_runs=3, min_passes=1)
def test_kill_broker_with_topic_leader(
    juju: jubilant.Juju,
    restore_state,
    restart_delay,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    # Let some time pass to create messages
    time.sleep(5)
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


@flaky.flaky(max_runs=3, min_passes=1)
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


@flaky.flaky(max_runs=3, min_passes=1)
def test_freeze_broker_with_topic_leader(
    juju: jubilant.Juju,
    restore_state,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    initial_leader_num = topic_description.leader

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
    assert topic_description.in_sync_replicas == {100, 101, 102}

    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)


@flaky.flaky(max_runs=3, min_passes=1)
def test_full_cluster_crash(
    juju: jubilant.Juju,
    restore_state,
    restart_delay,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    # Let some time pass for messages to be produced
    time.sleep(10)

    logger.info("Killing all brokers...")
    # kill all units "simultaneously"
    for unit in juju.status().apps[APP_NAME].units:
        send_control_signal(juju, unit, signal="SIGKILL")

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


@flaky.flaky(max_runs=3, min_passes=1)
def test_full_cluster_restart(
    juju: jubilant.Juju,
    restore_state,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    # Let some time pass for messages to be produced
    time.sleep(10)

    logger.info("Restarting all brokers...")
    # Restart all units "simultaneously"
    for unit in juju.status().apps[APP_NAME].units:
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


@flaky.flaky(max_runs=5, min_passes=1)
def test_pod_reschedule(
    juju: jubilant.Juju,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
    kafka_apps,
):
    # In case of retry, wait for all units active|idle
    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=3,
        successes=10,
        timeout=600,
    )

    # Let some time pass to create messages
    time.sleep(5)
    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    initial_leader_num = topic_description.leader

    logger.info(
        f"Killing pod of leader for topic '{ContinuousWrites.TOPIC_NAME}': {initial_leader_num}"
    )
    delete_pod(juju, unit_name=f"{APP_NAME}/{broker_id_to_unit_id(initial_leader_num)}")

    # let pod reschedule process be noticed up by juju
    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=3,
        successes=10,
        timeout=1000,
    )

    # refresh hosts with the new ip
    remove_k8s_hosts(juju=juju)
    add_k8s_hosts(juju=juju)

    # Check offsets after killing leader
    initial_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    time.sleep(CLIENT_TIMEOUT * 2)
    next_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    assert topic_description.in_sync_replicas == {100, 101, 102}

    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)


@flaky.flaky(max_runs=3, min_passes=1)
def test_network_cut_without_ip_change(
    juju: jubilant.Juju,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
    chaos_mesh,
):
    # Let some time pass for messages to be produced
    time.sleep(5)

    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    initial_leader_num = topic_description.leader

    logger.info(
        f"Cutting network for leader of topic '{ContinuousWrites.TOPIC_NAME}': {initial_leader_num}"
    )
    isolate_instance_from_cluster(
        juju=juju, unit_name=f"{APP_NAME}/{broker_id_to_unit_id(initial_leader_num)}"
    )
    time.sleep(REELECTION_TIME * 2)

    # verify replica is not in sync
    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    assert topic_description.in_sync_replicas == {100, 101, 102} - {initial_leader_num}
    assert initial_leader_num != topic_description.leader

    # verify new writes are continuing. Also, check that leader changed
    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    initial_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    time.sleep(CLIENT_TIMEOUT * 2)
    next_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)

    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    # Release the network
    logger.info(f"Releasing network of broker: {initial_leader_num}")
    remove_instance_isolation(juju)

    time.sleep(REELECTION_TIME * 2)

    result = c_writes.stop()
    time.sleep(CLIENT_TIMEOUT * 8)

    # verify the unit is now rejoined the cluster
    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    assert topic_description.in_sync_replicas == {100, 101, 102}

    assert_continuous_writes_consistency(result=result)
