#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import time

import pytest
from pytest_operator.plugin import OpsTest

from .helpers import (
    APP_NAME,
    DUMMY_NAME,
    REL_NAME_ADMIN,
    ZK_NAME,
    consume_and_check,
    produce_and_check_logs,
)

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker

CHANNEL = "3/stable"


@pytest.mark.abort_on_fail
async def test_in_place_upgrade(ops_test: OpsTest, kafka_charm, app_charm):
    await asyncio.gather(
        ops_test.model.deploy(
            ZK_NAME,
            channel="3/edge",
            application_name=ZK_NAME,
            num_units=1,
        ),
        ops_test.model.deploy(
            APP_NAME,
            application_name=APP_NAME,
            num_units=1,
            channel=CHANNEL,
        ),
        ops_test.model.deploy(app_charm, application_name=DUMMY_NAME, num_units=1, series="jammy"),
    )

    await ops_test.model.add_relation(APP_NAME, ZK_NAME)

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME, DUMMY_NAME], idle_period=30, timeout=1800, status="active"
    )

    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[ZK_NAME].status == "active"

    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME, DUMMY_NAME])

    await ops_test.model.applications[APP_NAME].add_units(count=2)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=600, idle_period=30, wait_for_exact_units=3
    )

    logger.info("Producing messages before upgrading")
    produce_and_check_logs(
        ops_test=ops_test,
        kafka_unit_name=f"{APP_NAME}/0",
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="hot-topic",
        replication_factor=3,
        num_partitions=1,
    )

    leader_unit = None
    for unit in ops_test.model.applications[APP_NAME].units:
        if await unit.is_leader_from_status():
            leader_unit = unit
    assert leader_unit

    logger.info("Calling pre-upgrade-check")
    action = await leader_unit.run_action("pre-upgrade-check")
    await action.wait()

    # ensure action completes
    time.sleep(10)

    logger.info("Upgrading Kafka...")
    await ops_test.model.applications[APP_NAME].refresh(path=kafka_charm)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=1000, idle_period=120
    )

    logger.info("Check that produced messages can be consumed afterwards")
    consume_and_check(
        ops_test=ops_test,
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="hot-topic",
    )
