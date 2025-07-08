#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from pytest_operator.plugin import OpsTest

from integration.ha.continuous_writes import ContinuousWrites
from integration.helpers.ha import (
    all_brokers_up,
    all_controllers_up,
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
from integration.helpers.pytest_operator import (
    APP_NAME,
    CONTROLLER_NAME,
    DUMMY_NAME,
    REL_NAME_ADMIN,
    SERIES,
    deploy_cluster,
)

logger = logging.getLogger(__name__)

USERNAME = "super"

CLIENT_TIMEOUT = 10
RESTART_DELAY = 60


@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
async def test_deploy_active(ops_test: OpsTest, kafka_charm, app_charm, kafka_apps):

    await asyncio.gather(
        deploy_cluster(
            ops_test=ops_test,
            charm=kafka_charm,
            kraft_mode="multi",
            num_broker=3,
            num_controller=3,
        ),
        ops_test.model.deploy(app_charm, application_name=DUMMY_NAME, num_units=1, series=SERIES),
    )
    await ops_test.model.wait_for_idle(
        apps=[*kafka_apps, DUMMY_NAME],
        idle_period=30,
        timeout=3600,
        status="active",
    )

    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    await ops_test.model.wait_for_idle(
        apps=[*kafka_apps, DUMMY_NAME], idle_period=60, status="active"
    )
    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[DUMMY_NAME].status == "active"


@pytest.mark.abort_on_fail
async def test_kill_leader_process(
    ops_test: OpsTest,
    restart_delay,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    """SIGKILLs leader process and checks recovery + re-election."""
    leader_name = await get_kraft_leader(ops_test)

    logger.info(f"Killing leader process on unit {leader_name}...")
    await send_control_signal(ops_test=ops_test, unit_name=leader_name, signal="SIGKILL")

    # Check that process is down
    assert await is_down(ops_test=ops_test, unit=leader_name)

    logger.info("Checking writes are increasing...")
    initial_offsets = await get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    await asyncio.sleep(CLIENT_TIMEOUT * 2)
    next_offsets = await get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    await asyncio.sleep(RESTART_DELAY * 2)

    logger.info("Checking leader re-election...")
    new_leader_name = get_kraft_leader(ops_test, unstable_unit=leader_name)
    assert new_leader_name != leader_name

    logger.info("Stopping continuous_writes...")
    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)

    await assert_quorum_healthy(ops_test=ops_test, kraft_mode="multi")
    # Assert all controllers & brokers have caught up. (all lags == 0)
    assert not any(get_kraft_quorum_lags(ops_test))


@pytest.mark.abort_on_fail
async def test_restart_leader_process(
    ops_test: OpsTest,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    """SIGTERMSs leader process and checks recovery + re-election."""
    leader_name = await get_kraft_leader(ops_test)

    logger.info(f"Restarting leader process on unit {leader_name}...")
    await send_control_signal(ops_test=ops_test, unit_name=leader_name, signal="SIGTERM")

    logger.info("Checking writes are increasing...")
    initial_offsets = await get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    await asyncio.sleep(CLIENT_TIMEOUT * 2)
    next_offsets = await get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    logger.info("Checking leader re-election...")
    new_leader_name = await get_kraft_leader(ops_test, unstable_unit=leader_name)
    assert new_leader_name != leader_name

    logger.info("Stopping continuous_writes...")
    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)

    await assert_quorum_healthy(ops_test=ops_test, kraft_mode="multi")
    # Assert all controllers & brokers have caught up (all lags == 0).
    assert not any(get_kraft_quorum_lags(ops_test))


@pytest.mark.abort_on_fail
async def test_freeze_leader_process(
    ops_test: OpsTest, c_writes: ContinuousWrites, c_writes_runner: ContinuousWrites
):
    """SIGSTOPs leader process and checks recovery + re-election after SIGCONT."""
    leader_name = await get_kraft_leader(ops_test)

    logger.info(f"Stopping leader process on unit {leader_name}...")
    await send_control_signal(ops_test=ops_test, unit_name=leader_name, signal="SIGSTOP")
    await asyncio.sleep(CLIENT_TIMEOUT * 3)  # to give time for re-election

    logger.info("Checking writes are increasing...")
    initial_offsets = await get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    await asyncio.sleep(CLIENT_TIMEOUT * 2)
    next_offsets = await get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    logger.info("Checking leader re-election...")
    new_leader_name = await get_kraft_leader(ops_test, unstable_unit=leader_name)
    assert new_leader_name != leader_name

    logger.info("Continuing initial leader process...")
    await send_control_signal(ops_test=ops_test, unit_name=leader_name, signal="SIGCONT")
    await asyncio.sleep(CLIENT_TIMEOUT * 3)  # letting writes continue while unit rejoins

    logger.info("Stopping continuous_writes...")
    result = c_writes.stop()
    await asyncio.sleep(CLIENT_TIMEOUT)  # buffer to ensure writes sync

    assert_continuous_writes_consistency(result=result)

    await assert_quorum_healthy(ops_test=ops_test, kraft_mode="multi")
    # Assert all controllers & brokers have caught up. (all lags == 0)
    assert not any(get_kraft_quorum_lags(ops_test))


async def test_full_cluster_crash(
    ops_test: OpsTest, restart_delay, c_writes: ContinuousWrites, c_writes_runner: ContinuousWrites
):
    # kill all units "simultaneously"
    await asyncio.gather(
        *[
            send_control_signal(ops_test, unit.name, signal="SIGKILL")
            for unit in ops_test.model.applications[CONTROLLER_NAME].units
        ]
    )

    # Check that all servers are down at the same time
    for unit in ops_test.model.applications[CONTROLLER_NAME].units:
        assert is_down(ops_test, unit.name)

    await asyncio.sleep(RESTART_DELAY * 2)

    logger.info("Checking writes are increasing...")
    initial_offsets = await get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    await asyncio.sleep(CLIENT_TIMEOUT * 2)
    next_offsets = await get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    logger.info("Stopping continuous_writes...")
    result = c_writes.stop()
    await asyncio.sleep(CLIENT_TIMEOUT)  # buffer to ensure writes sync

    assert_continuous_writes_consistency(result=result)

    await assert_quorum_healthy(ops_test=ops_test, kraft_mode="multi")
    # Assert all controllers & brokers have caught up. (all lags == 0)
    assert not any(get_kraft_quorum_lags(ops_test))


async def test_full_cluster_restart(
    ops_test: OpsTest, c_writes: ContinuousWrites, c_writes_runner: ContinuousWrites
):
    # kill all units "simultaneously"
    await asyncio.gather(
        *[
            send_control_signal(ops_test, unit.name, signal="SIGTERM")
            for unit in ops_test.model.applications[CONTROLLER_NAME].units
        ]
    )

    logger.info("Checking writes are increasing...")
    initial_offsets = await get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    await asyncio.sleep(CLIENT_TIMEOUT * 3)
    next_offsets = await get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    logger.info("Stopping continuous_writes...")
    result = c_writes.stop()
    await asyncio.sleep(CLIENT_TIMEOUT)  # buffer to ensure writes sync

    assert_continuous_writes_consistency(result=result)

    await assert_quorum_healthy(ops_test=ops_test, kraft_mode="multi")
    # Assert all controllers & brokers have caught up. (all lags == 0)
    assert not any(get_kraft_quorum_lags(ops_test))


@pytest.mark.abort_on_fail
async def test_network_cut_without_ip_change(
    ops_test: OpsTest, c_writes: ContinuousWrites, c_writes_runner: ContinuousWrites, restore_state
):
    """Cuts and restores network on leader, cluster self-heals after IP change."""
    leader_name = await get_kraft_leader(ops_test)
    leader_machine_name = await get_unit_machine_name(ops_test, leader_name)

    logger.info("Cutting leader network...")
    network_throttle(machine_name=leader_machine_name)
    await asyncio.sleep(CLIENT_TIMEOUT * 3)

    logger.info("Checking writes are increasing...")
    initial_offsets = await get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    await asyncio.sleep(CLIENT_TIMEOUT * 3)
    next_offsets = await get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    logger.info("Checking leader re-election...")
    new_leader_name = await get_kraft_leader(ops_test, unstable_unit=leader_name)
    assert new_leader_name != leader_name

    logger.info("Restoring leader network...")
    network_release(machine_name=leader_machine_name)
    await asyncio.sleep(CLIENT_TIMEOUT * 6)  # Give time for unit to rejoin

    logger.info("Stopping continuous_writes...")
    result = c_writes.stop()
    await asyncio.sleep(CLIENT_TIMEOUT)  # buffer to ensure writes sync

    assert_continuous_writes_consistency(result=result)

    await assert_quorum_healthy(ops_test=ops_test, kraft_mode="multi")
    # Assert all controllers & brokers have caught up. (all lags == 0)
    assert not any(get_kraft_quorum_lags(ops_test))


@pytest.mark.abort_on_fail
@pytest.mark.unstable(
    reason="Causes pytest-operator to be unstable. Hostname behaviour is somewhat tested during test_deploy_active_no_dnsmasq"
)
async def test_network_cut_self_heal(
    ops_test: OpsTest, c_writes: ContinuousWrites, c_writes_runner: ContinuousWrites, restore_state
):
    """Cuts and restores network on leader, cluster self-heals after IP change."""
    leader_name = await get_kraft_leader(ops_test)
    leader_machine_name = await get_unit_machine_name(ops_test, leader_name)

    logger.info("Cutting leader network...")
    network_cut(machine_name=leader_machine_name)
    await asyncio.sleep(
        CLIENT_TIMEOUT * 6
    )  # to give time for re-election, longer as network cut is weird

    logger.info("Checking writes are increasing...")
    initial_offsets = await get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    await asyncio.sleep(CLIENT_TIMEOUT * 3)
    next_offsets = await get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    logger.info("Checking leader re-election...")
    new_leader_name = await get_kraft_leader(ops_test, unstable_unit=leader_name)
    assert new_leader_name != leader_name

    logger.info("Restoring leader network...")
    network_restore(machine_name=leader_machine_name)

    logger.info("Waiting for Juju to detect new IP...")
    await all_brokers_up(ops_test)
    await all_controllers_up(ops_test, controller_app=CONTROLLER_NAME)

    logger.info("Stopping continuous_writes...")
    result = c_writes.stop()
    await asyncio.sleep(CLIENT_TIMEOUT)  # buffer to ensure writes sync

    assert_continuous_writes_consistency(result=result)

    await assert_quorum_healthy(ops_test=ops_test, kraft_mode="multi")
    # Assert all controllers & brokers have caught up. (all lags == 0)
    assert not any(get_kraft_quorum_lags(ops_test))
