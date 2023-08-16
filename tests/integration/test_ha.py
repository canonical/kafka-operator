#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from pytest_operator.plugin import OpsTest

from .helpers import (
    APP_NAME,
    REL_NAME_ADMIN,
    ZK_NAME,
    check_logs,
    produce_and_check_logs,
)

logger = logging.getLogger(__name__)


DUMMY_NAME = "app"


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, kafka_charm):
    await asyncio.gather(
        ops_test.model.deploy(kafka_charm, application_name=APP_NAME, num_units=1, series="jammy"),
        ops_test.model.deploy(ZK_NAME, channel="edge", num_units=1, series="jammy"),
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME], idle_period=30, timeout=3600)
    assert ops_test.model.applications[APP_NAME].status == "blocked"
    assert ops_test.model.applications[ZK_NAME].status == "active"

    await ops_test.model.add_relation(APP_NAME, ZK_NAME)
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME], idle_period=30)
        assert ops_test.model.applications[APP_NAME].status == "active"
        assert ops_test.model.applications[ZK_NAME].status == "active"


async def test_second_cluster(ops_test: OpsTest, kafka_charm, app_charm):
    second_kafka_name = f"{APP_NAME}-two"
    second_zk_name = f"{ZK_NAME}-two"

    await asyncio.gather(
        ops_test.model.deploy(
            kafka_charm, application_name=second_kafka_name, num_units=1, series="jammy"
        ),
        ops_test.model.deploy(
            ZK_NAME, channel="edge", application_name=second_zk_name, num_units=1, series="jammy"
        ),
        ops_test.model.deploy(app_charm, application_name=DUMMY_NAME, num_units=1, series="jammy"),
    )

    await ops_test.model.wait_for_idle(
        apps=[second_kafka_name, second_zk_name, DUMMY_NAME],
        idle_period=30,
        timeout=3600,
    )
    assert ops_test.model.applications[second_kafka_name].status == "blocked"

    await ops_test.model.add_relation(second_kafka_name, second_zk_name)

    # Relate "app" to the *first* cluster
    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")

    await ops_test.model.wait_for_idle(
        apps=[second_kafka_name, second_zk_name, DUMMY_NAME, APP_NAME],
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
