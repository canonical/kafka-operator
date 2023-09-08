#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import time

import pytest
from continuous_writes import ContinuousWrites
from pytest_operator.plugin import OpsTest
from tests.integration.ha.ha_helpers import (
    get_topic_leader,
    get_topic_offsets,
    send_control_signal,
)
from tests.integration.helpers import (
    APP_NAME,
    DUMMY_NAME,
    REL_NAME_ADMIN,
    ZK_NAME,
    check_logs,
    produce_and_check_logs,
)

logger = logging.getLogger(__name__)


@pytest.fixture()
async def c_writes(ops_test: OpsTest):
    """Creates instance of the ContinuousWrites."""
    app = APP_NAME
    return ContinuousWrites(ops_test, app)


@pytest.fixture()
async def c_writes_runner(ops_test: OpsTest, c_writes: ContinuousWrites):
    """Starts continuous write operations and clears writes at the end of the test."""
    await c_writes.start()
    yield
    await c_writes.clear()
    logger.info("\n\n\n\nThe writes have been cleared.\n\n\n\n")


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
    # check logs in the two remaining units
    check_logs(
        model_full_name=ops_test.model_full_name,
        kafka_unit_name=f"{APP_NAME}/1",
        topic="replicated-topic",
    )
    assert get_topic_offsets(
        ops_test=ops_test, topic="replicated-topic", unit_name=f"{APP_NAME}/1"
    ) == ["0", "15"]
    check_logs(
        model_full_name=ops_test.model_full_name,
        kafka_unit_name=f"{APP_NAME}/2",
        topic="replicated-topic",
    )
    assert get_topic_offsets(
        ops_test=ops_test, topic="replicated-topic", unit_name=f"{APP_NAME}/2"
    ) == ["0", "15"]


async def test_kill_broker_with_topic_leader(ops_test: OpsTest):
    initial_leader_num = await get_topic_leader(ops_test=ops_test, topic="replicated-topic")
    logger.info(f"Killing broker of leader for topic 'replicated-topic': {initial_leader_num}")
    await send_control_signal(
        ops_test=ops_test, unit_name=f"{APP_NAME}/{initial_leader_num}", kill_code="SIGKILL"
    )
    # Give time for the service to restart
    time.sleep(15)
    # Check that is still possible to write to the same topic.
    final_leader_num = await get_topic_leader(ops_test=ops_test, topic="replicated-topic")
    assert initial_leader_num != final_leader_num


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
