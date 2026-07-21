#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time

import jubilant
import pytest
from flaky import flaky

from integration.k8s.ha.continuous_writes import ContinuousWrites
from integration.k8s.helpers import (
    APP_NAME,
    CONTROLLER_NAME,
    DUMMY_NAME,
    REL_NAME_ADMIN,
    KRaftMode,
)
from integration.k8s.helpers.ha import (
    assert_all_brokers_up,
    assert_all_controllers_up,
    assert_continuous_writes_consistency,
    assert_quorum_healthy,
    assert_quorum_lag_is_zero,
    delete_pod,
    get_kraft_leader,
    get_topic_offsets,
    is_down,
    isolate_instance_from_cluster,
    remove_instance_isolation,
    send_control_signal,
)
from integration.k8s.helpers.jubilant import (
    all_active_idle,
    deploy_cluster,
)

logger = logging.getLogger(__name__)

CLIENT_TIMEOUT = 20
RESTART_DELAY = 60


@pytest.fixture(autouse=True)
def raise_if_not_kraft_multi(kraft_mode: KRaftMode):
    if kraft_mode != "multi":
        raise Exception("Controller HA tests should only run with --kraft-mode=multi")


@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
def test_deploy_active(juju: jubilant.Juju, kafka_charm, app_charm, kafka_apps):
    deploy_cluster(
        juju=juju,
        charm=kafka_charm,
        kraft_mode="multi",
        num_broker=3,
        num_controller=3,
    )
    juju.deploy(app_charm, app=DUMMY_NAME, num_units=1)

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
        timeout=600,
    )

    status = juju.status()
    assert status.apps[APP_NAME].app_status.current == "active"
    assert status.apps[DUMMY_NAME].app_status.current == "active"


@flaky(max_runs=3, min_passes=1)
def test_kill_leader_process(
    juju: jubilant.Juju,
    restart_delay,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    """SIGKILLs leader process and checks recovery + re-election."""
    leader_name = get_kraft_leader(juju)

    logger.info(f"Killing leader process on unit {leader_name}...")
    send_control_signal(juju=juju, unit_name=leader_name, signal="SIGKILL")

    # Check that process is down
    assert is_down(juju=juju, unit=leader_name)

    logger.info("Checking writes are increasing...")
    initial_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    time.sleep(CLIENT_TIMEOUT * 2)
    next_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    time.sleep(RESTART_DELAY * 2)

    logger.info("Checking leader re-election...")
    new_leader_name = get_kraft_leader(juju, unstable_unit=leader_name)
    assert new_leader_name != leader_name

    logger.info("Stopping continuous_writes...")
    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)

    assert_quorum_healthy(juju=juju, kraft_mode="multi")
    # Assert all controllers & brokers have caught up. (all lags == 0)
    assert_quorum_lag_is_zero(juju=juju)


@flaky(max_runs=3, min_passes=1)
def test_restart_leader_process(
    juju: jubilant.Juju,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    """SIGTERMSs leader process and checks recovery + re-election."""
    leader_name = get_kraft_leader(juju)

    logger.info(f"Restarting leader process on unit {leader_name}...")
    send_control_signal(juju=juju, unit_name=leader_name, signal="SIGTERM")

    logger.info("Checking writes are increasing...")
    initial_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    time.sleep(CLIENT_TIMEOUT * 2)
    next_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    logger.info("Checking leader re-election...")
    new_leader_name = get_kraft_leader(juju, unstable_unit=leader_name)
    assert new_leader_name != leader_name

    logger.info("Stopping continuous_writes...")
    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)

    assert_quorum_healthy(juju=juju, kraft_mode="multi")
    # Assert all controllers & brokers have caught up (all lags == 0).
    assert_quorum_lag_is_zero(juju=juju)


@flaky(max_runs=3, min_passes=1)
def test_freeze_leader_process(
    juju: jubilant.Juju, c_writes: ContinuousWrites, c_writes_runner: ContinuousWrites
):
    """SIGSTOPs leader process and checks recovery + re-election after SIGCONT."""
    leader_name = get_kraft_leader(juju)

    logger.info(f"Stopping leader process on unit {leader_name}...")
    send_control_signal(juju=juju, unit_name=leader_name, signal="SIGSTOP")
    time.sleep(CLIENT_TIMEOUT * 3)  # to give time for re-election

    logger.info("Checking writes are increasing...")
    initial_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    time.sleep(CLIENT_TIMEOUT * 2)
    next_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    logger.info("Checking leader re-election...")
    new_leader_name = get_kraft_leader(juju, unstable_unit=leader_name)
    assert new_leader_name != leader_name

    logger.info("Continuing initial leader process...")
    send_control_signal(juju=juju, unit_name=leader_name, signal="SIGCONT")
    time.sleep(CLIENT_TIMEOUT * 3)  # letting writes continue while unit rejoins

    logger.info("Stopping continuous_writes...")
    result = c_writes.stop()
    time.sleep(CLIENT_TIMEOUT)  # buffer to ensure writes sync

    assert_continuous_writes_consistency(result=result)

    assert_quorum_healthy(juju=juju, kraft_mode="multi")
    # Assert all controllers & brokers have caught up. (all lags == 0)
    assert_quorum_lag_is_zero(juju=juju)


@flaky(max_runs=3, min_passes=1)
def test_full_cluster_crash(
    juju: jubilant.Juju,
    restart_delay,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    # kill all units "simultaneously"
    units = juju.status().apps[CONTROLLER_NAME].units
    for unit in units:
        send_control_signal(juju, unit, signal="SIGKILL")

    # Check that all servers are down at the same time
    for unit in units:
        assert is_down(juju, unit)

    time.sleep(RESTART_DELAY * 2)

    logger.info("Checking writes are increasing...")
    initial_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    time.sleep(CLIENT_TIMEOUT * 2)
    next_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    logger.info("Stopping continuous_writes...")
    result = c_writes.stop()
    time.sleep(CLIENT_TIMEOUT)  # buffer to ensure writes sync

    assert_continuous_writes_consistency(result=result)

    assert_quorum_healthy(juju=juju, kraft_mode="multi")
    # Assert all controllers & brokers have caught up. (all lags == 0)
    assert_quorum_lag_is_zero(juju=juju)


@flaky(max_runs=3, min_passes=1)
def test_full_cluster_restart(
    juju: jubilant.Juju, c_writes: ContinuousWrites, c_writes_runner: ContinuousWrites
):
    # kill all units "simultaneously"
    units = juju.status().apps[CONTROLLER_NAME].units
    for unit in units:
        send_control_signal(juju, unit, signal="SIGTERM")

    logger.info("Checking writes are increasing...")
    initial_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    time.sleep(CLIENT_TIMEOUT * 3)
    next_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    logger.info("Stopping continuous_writes...")
    result = c_writes.stop()
    time.sleep(CLIENT_TIMEOUT)  # buffer to ensure writes sync

    assert_continuous_writes_consistency(result=result)

    assert_quorum_healthy(juju=juju, kraft_mode="multi")
    # Assert all controllers & brokers have caught up. (all lags == 0)
    assert_quorum_lag_is_zero(juju=juju)


@flaky(max_runs=5, min_passes=1)
def test_pod_reschedule(
    juju: jubilant.Juju,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
    kafka_apps,
):
    """Forcefully reschedules controller pod."""
    # In case of retry, wait for all units active|idle
    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=3,
        successes=10,
        timeout=600,
    )

    assert juju.model
    leader_name = get_kraft_leader(juju)
    logger.info("Removing leader pod...")
    delete_pod(juju=juju, unit_name=leader_name)
    time.sleep(CLIENT_TIMEOUT)  # waiting for process to restore

    logger.info("Checking leader changed...")
    new_leader_name = get_kraft_leader(juju, unstable_unit=leader_name)
    assert new_leader_name != leader_name  # ensures pod was actually rescheduled

    logger.info("Checking writes are increasing...")
    initial_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    time.sleep(CLIENT_TIMEOUT * 3)
    next_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    logger.info("Stopping continuous_writes...")
    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)

    assert_quorum_healthy(juju=juju, kraft_mode="multi")
    # Assert all controllers & brokers have caught up. (all lags == 0)
    assert_quorum_lag_is_zero(juju=juju)


@pytest.mark.skip(reason="deploy_chaos_mesh.sh fails on SH runners, needs investigation.")
@pytest.mark.abort_on_fail
def test_network_cut_without_ip_change(
    juju: jubilant.Juju,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
    chaos_mesh,
):
    """Cuts and restores network on leader, cluster self-heals after IP change."""
    leader_name = get_kraft_leader(juju)
    isolate_instance_from_cluster(juju=juju, unit_name=leader_name)
    time.sleep(CLIENT_TIMEOUT * 3)

    logger.info("Checking writes are increasing...")
    initial_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    time.sleep(CLIENT_TIMEOUT * 3)
    next_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    logger.info("Checking leader re-election...")
    new_leader_name = get_kraft_leader(juju, unstable_unit=leader_name)
    assert new_leader_name != leader_name

    logger.info("Restoring leader network...")
    remove_instance_isolation(juju)
    time.sleep(CLIENT_TIMEOUT * 6)  # Give time for unit to rejoin

    logger.info("Stopping continuous_writes...")
    result = c_writes.stop()
    time.sleep(CLIENT_TIMEOUT)  # buffer to ensure writes sync

    assert_all_brokers_up(juju)
    assert_all_controllers_up(juju, controller_app=CONTROLLER_NAME)

    assert_continuous_writes_consistency(result=result)

    assert_quorum_healthy(juju=juju, kraft_mode="multi")
    # Assert all controllers & brokers have caught up. (all lags == 0)
    assert_quorum_lag_is_zero(juju=juju)
