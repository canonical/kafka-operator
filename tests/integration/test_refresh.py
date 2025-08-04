#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time

import pytest
from pytest_operator.plugin import OpsTest

from integration.helpers.pytest_operator import (
    APP_NAME,
    DUMMY_NAME,
    REL_NAME_ADMIN,
    SERIES,
    consume_and_check,
    deploy_cluster,
    produce_and_check_logs,
)

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker


@pytest.mark.abort_on_fail
async def test_in_place_upgrade(
    ops_test: OpsTest, kafka_charm, app_charm, kraft_mode, controller_app
):
    await deploy_cluster(
        ops_test=ops_test,
        charm=kafka_charm,
        kraft_mode=kraft_mode,
    )

    await ops_test.model.deploy(
        app_charm,
        application_name=DUMMY_NAME,
        num_units=1,
        series=SERIES,
    )

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, controller_app, DUMMY_NAME], idle_period=30, timeout=1800, status="active"
    )

    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[controller_app].status == "active"

    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    await ops_test.model.wait_for_idle(apps=[APP_NAME, controller_app, DUMMY_NAME])

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

    logger.info("Calling pre-refresh-check")
    action = await leader_unit.run_action("pre-refresh-check")
    await action.wait()

    # ensure action completes
    time.sleep(10)

    logger.info("Upgrading Kafka...")
    await ops_test.model.applications[APP_NAME].refresh(path=kafka_charm)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, controller_app], status="active", timeout=1000, idle_period=120
    )

    logger.info("Check that produced messages can be consumed afterwards")
    consume_and_check(
        ops_test=ops_test,
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="hot-topic",
    )


@pytest.mark.abort_on_fail
async def test_controller_upgrade_multinode(
    ops_test: OpsTest, kafka_charm, kraft_mode, controller_app
):
    """Test upgrading the controller separately in multi-node mode."""
    if kraft_mode != "multi":
        logger.info(f"Skipping controller upgrade test because we're using {kraft_mode} mode.")
        return

    logger.info("Producing messages before controller upgrade")
    produce_and_check_logs(
        ops_test=ops_test,
        kafka_unit_name=f"{APP_NAME}/0",
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="controller-upgrade-topic",
        replication_factor=3,
        num_partitions=1,
    )

    # Find controller leader unit
    controller_leader_unit = None
    for unit in ops_test.model.applications[controller_app].units:
        if await unit.is_leader_from_status():
            controller_leader_unit = unit
    assert controller_leader_unit

    logger.info("Calling pre-refresh-check on controller")
    action = await controller_leader_unit.run_action("pre-refresh-check")
    await action.wait()

    # ensure action completes
    time.sleep(10)

    logger.info("Upgrading Controller...")
    await ops_test.model.applications[controller_app].refresh(path=kafka_charm)
    await ops_test.model.wait_for_idle(
        apps=[controller_app], status="active", timeout=1000, idle_period=120
    )

    # Ensure brokers are still active after controller upgrade
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=600, idle_period=30
    )

    logger.info("Check that produced messages can still be consumed after controller upgrade")
    consume_and_check(
        ops_test=ops_test,
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="controller-upgrade-topic",
    )
