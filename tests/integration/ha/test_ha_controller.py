#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time

import jubilant
import pytest

from integration.ha.continuous_writes import ContinuousWrites
from integration.helpers import (
    APP_NAME,
    CONTROLLER_NAME,
    DUMMY_NAME,
    REL_NAME_ADMIN,
)
from integration.helpers.ha import (
    assert_all_brokers_up,
    assert_all_controllers_up,
    assert_continuous_writes_consistency,
    assert_quorum_healthy,
    get_kraft_leader,
    get_kraft_quorum_lags,
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
    deploy_cluster,
)

logger = logging.getLogger(__name__)

USERNAME = "super"

CLIENT_TIMEOUT = 10
RESTART_DELAY = 60


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
        timeout=600,
    )

    status = juju.status()
    assert status.apps[APP_NAME].app_status.current == "active"
    assert status.apps[DUMMY_NAME].app_status.current == "active"


@pytest.mark.abort_on_fail
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
    assert not any(get_kraft_quorum_lags(juju))


@pytest.mark.abort_on_fail
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
    assert not any(get_kraft_quorum_lags(juju))


@pytest.mark.abort_on_fail
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
    assert not any(get_kraft_quorum_lags(juju))


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
    assert not any(get_kraft_quorum_lags(juju))


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
    assert not any(get_kraft_quorum_lags(juju))


@pytest.mark.abort_on_fail
def test_network_cut_without_ip_change(
    juju: jubilant.Juju,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
    restore_state,
):
    """Cuts and restores network on leader, cluster self-heals after IP change."""
    leader_name = get_kraft_leader(juju)
    leader_machine_name = get_unit_machine_name(juju, leader_name)

    logger.info("Cutting leader network...")
    network_throttle(machine_name=leader_machine_name)
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
    network_release(machine_name=leader_machine_name)
    time.sleep(CLIENT_TIMEOUT * 6)  # Give time for unit to rejoin

    logger.info("Stopping continuous_writes...")
    result = c_writes.stop()
    time.sleep(CLIENT_TIMEOUT)  # buffer to ensure writes sync

    assert_continuous_writes_consistency(result=result)

    assert_quorum_healthy(juju=juju, kraft_mode="multi")
    # Assert all controllers & brokers have caught up. (all lags == 0)
    assert not any(get_kraft_quorum_lags(juju))


# TODO: enable after IP change handling of the charm is fixed.
@pytest.mark.skip(reason="IP change is not handled gracefully, leading to unpredictable results")
def test_network_cut_self_heal(
    juju: jubilant.Juju,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
    restore_state,
):
    """Cuts and restores network on leader, cluster self-heals after IP change."""
    leader_name = get_kraft_leader(juju)
    leader_machine_name = get_unit_machine_name(juju, leader_name)

    logger.info("Cutting leader network...")
    network_cut(machine_name=leader_machine_name)
    time.sleep(CLIENT_TIMEOUT * 6)  # to give time for re-election, longer as network cut is weird

    logger.info("Checking writes are increasing...")
    initial_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    time.sleep(CLIENT_TIMEOUT * 3)
    next_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    logger.info("Checking leader re-election...")
    new_leader_name = get_kraft_leader(juju, unstable_unit=leader_name)
    assert new_leader_name != leader_name

    logger.info("Restoring leader network...")
    network_restore(machine_name=leader_machine_name)

    logger.info("Waiting for Juju to detect new IP...")
    assert_all_brokers_up(juju)
    assert_all_controllers_up(juju, controller_app=CONTROLLER_NAME)

    logger.info("Stopping continuous_writes...")
    result = c_writes.stop()
    time.sleep(CLIENT_TIMEOUT)  # buffer to ensure writes sync

    assert_continuous_writes_consistency(result=result)

    assert_quorum_healthy(juju=juju, kraft_mode="multi")
    # Assert all controllers & brokers have caught up. (all lags == 0)
    assert not any(get_kraft_quorum_lags(juju))
