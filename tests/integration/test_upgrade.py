#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from pytest_operator.plugin import OpsTest

from literals import TLS_RELATION

from .helpers import (
    APP_NAME,
    DUMMY_NAME,
    KAFKA_CONTAINER,
    REL_NAME_ADMIN,
    TLS_NAME,
    ZK_NAME,
    check_logs,
)

logger = logging.getLogger(__name__)

CHANNEL = "3/stable"


@pytest.mark.abort_on_fail
async def test_in_place_upgrade(ops_test: OpsTest, kafka_charm):
    """Tests happy path upgrade with TLS."""
    tls_config = {"ca-common-name": "kafka"}

    await asyncio.gather(
        ops_test.model.deploy(
            ZK_NAME,
            channel=CHANNEL,
            application_name=ZK_NAME,
            num_units=1,
            trust=True,
        ),
        ops_test.model.deploy(
            APP_NAME,
            application_name=APP_NAME,
            num_units=1,
            channel=CHANNEL,
            trust=True,
        ),
        ops_test.model.deploy(
            TLS_NAME, channel="edge", config=tls_config, revision=163, trust=True
        ),
    )

    await asyncio.gather(
        ops_test.model.add_relation(APP_NAME, ZK_NAME),
        ops_test.model.add_relation(ZK_NAME, TLS_NAME),
        ops_test.model.add_relation(f"{APP_NAME}:{TLS_RELATION}", TLS_NAME),
    )

    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, ZK_NAME, TLS_NAME],
            idle_period=30,
            timeout=1800,
            status="active",
            raise_on_error=False,
        )

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME, TLS_NAME], status="active", idle_period=30
    )

    await ops_test.model.applications[APP_NAME].add_units(count=2)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=600, idle_period=30, wait_for_exact_units=3
    )

    leader_unit = None
    for unit in ops_test.model.applications[APP_NAME].units:
        if await unit.is_leader_from_status():
            leader_unit = unit
    assert leader_unit

    logger.info("Calling pre-upgrade-check...")
    action = await leader_unit.run_action("pre-upgrade-check")
    await action.wait()
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], timeout=1000, idle_period=15, status="active"
    )

    logger.info("Upgrading Kafka...")
    await ops_test.model.applications[APP_NAME].refresh(
        path=kafka_charm,
        resources={"kafka-image": KAFKA_CONTAINER},
    )

    async with ops_test.fast_forward(fast_interval="20s"):
        await asyncio.sleep(90)

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], timeout=1000, idle_period=180, raise_on_error=False
    )

    action = await leader_unit.run_action("resume-upgrade")
    await action.wait()
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], timeout=1000, idle_period=30, status="active"
    )

    # cleanup existing 'current' Kafka, and remove TLS for next test
    await ops_test.model.remove_application(APP_NAME, block_until_done=True)
    await ops_test.model.remove_application(TLS_NAME, block_until_done=True)
    await ops_test.model.wait_for_idle(
        apps=[ZK_NAME], timeout=1800, idle_period=30, status="active"
    )


@pytest.mark.abort_on_fail
async def test_in_place_upgrade_consistency(ops_test: OpsTest, kafka_charm, app_charm):
    """Tests non-TLS upgrade data consistency during upgrade."""
    await asyncio.gather(
        ops_test.model.deploy(
            APP_NAME,
            application_name=APP_NAME,
            num_units=1,
            channel=CHANNEL,
            trust=True,
        ),
        ops_test.model.deploy(
            app_charm, application_name=DUMMY_NAME, num_units=1, series="jammy", trust=True
        ),
    )

    await ops_test.model.add_relation(APP_NAME, ZK_NAME)

    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, ZK_NAME, DUMMY_NAME],
            idle_period=30,
            timeout=1800,
            status="active",
            raise_on_error=False,
        )

    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME, DUMMY_NAME], status="active", idle_period=30
    )

    await ops_test.model.applications[APP_NAME].add_units(count=2)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=600, idle_period=30, wait_for_exact_units=3
    )

    logger.info("Producing messages before upgrading...")
    action = await ops_test.model.units.get(f"{DUMMY_NAME}/0").run_action("produce")
    await action.wait()
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, DUMMY_NAME], timeout=1000, idle_period=30, status="active"
    )

    check_logs(
        ops_test=ops_test,
        kafka_unit_name=f"{APP_NAME}/0",
        topic="test-topic",
    )

    leader_unit = None
    for unit in ops_test.model.applications[APP_NAME].units:
        if await unit.is_leader_from_status():
            leader_unit = unit
    assert leader_unit

    logger.info("Calling pre-upgrade-check...")
    action = await leader_unit.run_action("pre-upgrade-check")
    await action.wait()
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, DUMMY_NAME], timeout=1000, idle_period=15, status="active"
    )

    logger.info("Upgrading Kafka...")
    await ops_test.model.applications[APP_NAME].refresh(
        path=kafka_charm,
        resources={"kafka-image": KAFKA_CONTAINER},
    )

    async with ops_test.fast_forward(fast_interval="20s"):
        await asyncio.sleep(90)

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, DUMMY_NAME], timeout=1000, idle_period=180, raise_on_error=False
    )

    action = await leader_unit.run_action("resume-upgrade")
    await action.wait()
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, DUMMY_NAME], timeout=1000, idle_period=30, status="active"
    )

    logger.info("Checking that produced messages can be consumed afterwards...")
    action = await ops_test.model.units.get(f"{DUMMY_NAME}/0").run_action("consume")
    await action.wait()
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, DUMMY_NAME], timeout=1000, idle_period=30, status="active"
    )
