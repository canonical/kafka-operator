#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from pytest_operator.plugin import OpsTest

from integration.ha.continuous_writes import ContinuousWrites
from integration.ha.ha_helpers import (
    assert_continuous_writes_consistency,
    get_topic_description,
    get_topic_offsets,
    is_up,
    patch_restart_delay,
    remove_restart_delay,
    send_control_signal,
)
from integration.helpers import (
    APP_NAME,
    DUMMY_NAME,
    REL_NAME_ADMIN,
    TEST_DEFAULT_MESSAGES,
    ZK_NAME,
    check_logs,
    produce_and_check_logs,
)

RESTART_DELAY = 60
CLIENT_TIMEOUT = 30

logger = logging.getLogger(__name__)


@pytest.fixture()
async def c_writes(ops_test: OpsTest):
    """Creates instance of the ContinuousWrites."""
    app = APP_NAME
    return ContinuousWrites(ops_test, app)


@pytest.fixture()
async def c_writes_runner(ops_test: OpsTest, c_writes: ContinuousWrites):
    """Starts continuous write operations and clears writes at the end of the test."""
    c_writes.start()
    yield
    c_writes.clear()
    logger.info("\n\n\n\nThe writes have been cleared.\n\n\n\n")


@pytest.fixture()
async def restart_delay(ops_test: OpsTest):
    for unit in ops_test.model.applications[APP_NAME].units:
        await patch_restart_delay(ops_test=ops_test, unit_name=unit.name, delay=RESTART_DELAY)
    yield
    for unit in ops_test.model.applications[APP_NAME].units:
        await remove_restart_delay(ops_test=ops_test, unit_name=unit.name)


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, kafka_charm, app_charm):
    await asyncio.gather(
        ops_test.model.deploy(kafka_charm, application_name=APP_NAME, num_units=1, series="jammy"),
        ops_test.model.deploy(ZK_NAME, channel="edge", num_units=1, series="jammy"),
        ops_test.model.deploy(app_charm, application_name=DUMMY_NAME, num_units=1, series="jammy"),
    )
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME, DUMMY_NAME],
        idle_period=30,
        timeout=3600,
    )
    assert ops_test.model.applications[APP_NAME].status == "blocked"
    assert ops_test.model.applications[ZK_NAME].status == "active"

    await ops_test.model.add_relation(APP_NAME, ZK_NAME)
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME], idle_period=30)
        assert ops_test.model.applications[APP_NAME].status == "active"
        assert ops_test.model.applications[ZK_NAME].status == "active"

    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    await ops_test.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME], idle_period=30)
    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[DUMMY_NAME].status == "active"


async def test_replicated_events(ops_test: OpsTest):
    await ops_test.model.applications[APP_NAME].add_units(count=2)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=600, idle_period=120, wait_for_exact_units=3
    )
    logger.info("Producing messages and checking on all units")
    produce_and_check_logs(
        model_full_name=ops_test.model_full_name,
        kafka_unit_name=f"{APP_NAME}/0",
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="replicated-topic",
        replication_factor=3,
        num_partitions=1,
    )
    topic_description = await get_topic_description(ops_test, "replicated-topic")

    assert topic_description.in_sync_replicas == {0, 1, 2}
    # check offsets in the two remaining units
    assert await get_topic_offsets(ops_test=ops_test, topic="replicated-topic") == [
        "0",
        str(TEST_DEFAULT_MESSAGES),
    ]


async def test_kill_broker_with_topic_leader(
    ops_test: OpsTest,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
    restart_delay,
):
    topic_description = await get_topic_description(
        ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME
    )
    initial_leader_num = topic_description.leader
    initial_offsets = await get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)

    logger.info(
        f"Killing broker of leader for topic '{ContinuousWrites.TOPIC_NAME}': {initial_leader_num}"
    )
    await send_control_signal(
        ops_test=ops_test, unit_name=f"{APP_NAME}/{initial_leader_num}", signal="SIGKILL"
    )

    # verify replica is not in sync
    topic_description = await get_topic_description(
        ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME
    )
    assert topic_description.in_sync_replicas == {0, 1, 2} - {initial_leader_num}

    # Give time for the service to restart
    await asyncio.sleep(RESTART_DELAY * 2)

    # Check that leader changed
    topic_description = await get_topic_description(
        ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME
    )
    next_leader_num = topic_description.leader
    next_offsets = await get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)

    assert topic_description.in_sync_replicas == {0, 1, 2}
    assert initial_leader_num != next_leader_num
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)


async def test_restart_broker_with_topic_leader(
    ops_test: OpsTest,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    topic_description = await get_topic_description(
        ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME
    )
    leader_num = topic_description.leader
    initial_offsets = await get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)

    logger.info(
        f"Restarting broker of leader for topic '{ContinuousWrites.TOPIC_NAME}': {leader_num}"
    )
    await send_control_signal(
        ops_test=ops_test, unit_name=f"{APP_NAME}/{leader_num}", signal="SIGTERM"
    )
    # Give time for the service to restart
    await asyncio.sleep(10)

    topic_description = await get_topic_description(
        ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME
    )
    next_offsets = await get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)

    assert topic_description.in_sync_replicas == {0, 1, 2}
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)


async def test_freeze_broker_with_topic_leader(
    ops_test: OpsTest,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    topic_description = await get_topic_description(
        ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME
    )
    initial_leader_num = topic_description.leader

    logger.info(
        f"Freezing broker of leader for topic '{ContinuousWrites.TOPIC_NAME}': {initial_leader_num}"
    )
    await send_control_signal(
        ops_test=ops_test, unit_name=f"{APP_NAME}/{initial_leader_num}", signal="SIGSTOP"
    )
    await asyncio.sleep(25)

    # verify replica is not in sync
    topic_description = await get_topic_description(
        ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME
    )
    assert topic_description.in_sync_replicas == {0, 1, 2} - {initial_leader_num}
    assert not is_up(
        ops_test=ops_test, broker_id=initial_leader_num
    ), f"Broker {initial_leader_num} reported as up"

    # verify new writes are continuing by counting the number of writes before and after 5 seconds.
    # Also, check that leader changed
    topic_description = await get_topic_description(
        ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME
    )
    next_leader_num = topic_description.leader
    initial_offsets = await get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    await asyncio.sleep(CLIENT_TIMEOUT)
    next_offsets = await get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)

    assert initial_leader_num != next_leader_num
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    # Un-freeze the process
    logger.info(f"Un-freezing broker: {initial_leader_num}")
    await send_control_signal(
        ops_test=ops_test, unit_name=f"{APP_NAME}/{initial_leader_num}", signal="SIGCONT"
    )
    await asyncio.sleep(15)
    topic_description = await get_topic_description(
        ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME
    )

    # verify the unit is now rejoined the cluster
    assert is_up(
        ops_test=ops_test, broker_id=initial_leader_num
    ), f"Broker {initial_leader_num} reported as down"
    assert topic_description.in_sync_replicas == {0, 1, 2}

    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)


async def test_full_cluster_crash(
    ops_test: OpsTest,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
    restart_delay,
):
    # Let some time pass for messages to be produced
    await asyncio.sleep(10)

    logger.info("Killing all brokers...")
    # kill all units "simultaneously"
    await asyncio.gather(
        *[
            send_control_signal(ops_test, unit.name, signal="SIGKILL")
            for unit in ops_test.model.applications[APP_NAME].units
        ]
    )
    # Give time for the service to restart
    await asyncio.sleep(RESTART_DELAY * 2)

    topic_description = await get_topic_description(
        ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME
    )
    initial_offsets = await get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    await asyncio.sleep(CLIENT_TIMEOUT * 2)
    next_offsets = await get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)

    assert int(next_offsets[-1]) > int(initial_offsets[-1])
    assert topic_description.in_sync_replicas == {0, 1, 2}

    result = c_writes.stop()
    assert_continuous_writes_consistency(
        result=result,
        expected_lost_messages=1,
        compare_lost_messages=True,
    )


async def test_full_cluster_restart(
    ops_test: OpsTest,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    # Let some time pass for messages to be produced
    await asyncio.sleep(10)

    logger.info("Restarting all brokers...")
    # Restart all units "simultaneously"
    await asyncio.gather(
        *[
            send_control_signal(ops_test, unit.name, signal="SIGTERM")
            for unit in ops_test.model.applications[APP_NAME].units
        ]
    )
    # Give time for the service to restart
    await asyncio.sleep(15)

    initial_offsets = await get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    await asyncio.sleep(CLIENT_TIMEOUT * 2)
    next_offsets = await get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    topic_description = await get_topic_description(
        ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME
    )

    assert int(next_offsets[-1]) > int(initial_offsets[-1])
    assert topic_description.in_sync_replicas == {0, 1, 2}

    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)


@pytest.mark.skip
async def test_multi_cluster_isolation(ops_test: OpsTest, kafka_charm):
    second_kafka_name = f"{APP_NAME}-two"
    second_zk_name = f"{ZK_NAME}-two"

    await asyncio.gather(
        ops_test.model.deploy(
            kafka_charm, application_name=second_kafka_name, num_units=1, series="jammy"
        ),
        ops_test.model.deploy(
            ZK_NAME, channel="edge", application_name=second_zk_name, num_units=1, series="jammy"
        ),
    )

    await ops_test.model.wait_for_idle(
        apps=[second_kafka_name, second_zk_name],
        idle_period=30,
        timeout=3600,
    )
    assert ops_test.model.applications[second_kafka_name].status == "blocked"

    await ops_test.model.add_relation(second_kafka_name, second_zk_name)
    await ops_test.model.wait_for_idle(
        apps=[second_kafka_name, second_zk_name, APP_NAME],
        idle_period=30,
    )

    produce_and_check_logs(
        model_full_name=ops_test.model_full_name,
        kafka_unit_name=f"{APP_NAME}/0",
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="hot-topic",
    )

    # Check that logs are not found on the second cluster
    with pytest.raises(AssertionError):
        check_logs(
            model_full_name=ops_test.model_full_name,
            kafka_unit_name=f"{second_kafka_name}/0",
            topic="hot-topic",
        )
