#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from ha_helpers import (
    APP_NAME,
    REL_NAME_ADMIN,
    ZK_NAME,
    check_logs,
    get_kafka_zk_relation_data,
    get_topic_leader,
    kill_unit_process,
    produce_and_check_logs,
)
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


DUMMY_NAME = "app"


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


@pytest.mark.skip
async def test_second_cluster(ops_test: OpsTest, kafka_charm):
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


async def test_replicated_events(ops_test: OpsTest):
    await ops_test.model.applications[APP_NAME].add_units(count=2)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=600, idle_period=120, wait_for_exact_units=3
    )

    produce_and_check_logs(
        model_full_name=ops_test.model_full_name,
        kafka_unit_name=f"{APP_NAME}/0",
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="replicated-topic",
    )
    # check logs in the two remaining units
    check_logs(
        model_full_name=ops_test.model_full_name,
        kafka_unit_name=f"{APP_NAME}/1",
        topic="replicated-topic",
    )
    check_logs(
        model_full_name=ops_test.model_full_name,
        kafka_unit_name=f"{APP_NAME}/2",
        topic="replicated-topic",
    )


async def test_remove_topic_leader(ops_test: OpsTest):
    relation_data = get_kafka_zk_relation_data(
        unit_name=f"{APP_NAME}/0", model_full_name=ops_test.model_full_name
    )
    uri = relation_data["uris"].split(",")[-1]

    leader_num = get_topic_leader(
        model_full_name=ops_test.model_full_name,
        zookeeper_uri=uri,
        topic="replicated-topic",
    )

    await kill_unit_process(
        ops_test=ops_test, unit_name=f"{APP_NAME}/{leader_num}", kill_code="SIGKILL"
    )
    # Check that is still possible to write to the same topic.
    produce_and_check_logs(
        model_full_name=ops_test.model_full_name,
        kafka_unit_name=f"{APP_NAME}/0",
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="replicated-topic",
    )
