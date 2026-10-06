#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from pytest_operator.plugin import OpsTest

from .helpers import (
    APP_NAME,
    KAFKA_CONTAINER,
    ZK_NAME,
    get_active_brokers,
    get_address,
    get_kafka_zk_relation_data,
)

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
async def test_kafka_simple_scale_up(ops_test: OpsTest, kafka_charm):
    await asyncio.gather(
        ops_test.model.deploy(
            ZK_NAME, channel="3/edge", application_name=ZK_NAME, num_units=1, trust=True
        ),
        ops_test.model.deploy(
            kafka_charm,
            application_name=APP_NAME,
            num_units=1,
            resources={"kafka-image": KAFKA_CONTAINER},
            trust=True,
            config={"expose_external": "nodeport"},
        ),
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME])
    await ops_test.model.add_relation(APP_NAME, ZK_NAME)

    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, ZK_NAME], timeout=1000, status="active", idle_period=20
        )

    await ops_test.model.applications[APP_NAME].scale(scale=3)
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[APP_NAME].units) == 3)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=1000, idle_period=40
    )

    kafka_zk_relation_data = get_kafka_zk_relation_data(
        ops_test=ops_test,
        unit_name=f"{APP_NAME}/2",
        owner=ZK_NAME,
    )

    # can't use *-endpoints address from outside of K8s cluster, need to patch
    zookeeper_address = await get_address(ops_test, app_name=ZK_NAME)
    kafka_zk_relation_data["endpoints"] = zookeeper_address

    active_brokers = get_active_brokers(config=kafka_zk_relation_data)

    chroot = kafka_zk_relation_data.get("database", kafka_zk_relation_data.get("chroot", ""))
    assert f"{chroot}/brokers/ids/0" in active_brokers
    assert f"{chroot}/brokers/ids/1" in active_brokers
    assert f"{chroot}/brokers/ids/2" in active_brokers


@pytest.mark.abort_on_fail
async def test_kafka_simple_scale_down(ops_test: OpsTest):
    await ops_test.model.applications[APP_NAME].scale(scale=2)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=1000, idle_period=30, wait_for_exact_units=2
    )

    # ensuring ZK data gets updated
    async with ops_test.fast_forward(fast_interval="20s"):
        await asyncio.sleep(60)

    kafka_zk_relation_data = get_kafka_zk_relation_data(
        ops_test=ops_test,
        unit_name=f"{APP_NAME}/1",
        owner=ZK_NAME,
    )

    # can't use *-endpoints address from outside of K8s cluster, need to patch
    zookeeper_address = await get_address(ops_test, app_name=ZK_NAME)
    kafka_zk_relation_data["endpoints"] = zookeeper_address

    active_brokers = get_active_brokers(config=kafka_zk_relation_data)
    chroot = kafka_zk_relation_data.get("database", kafka_zk_relation_data.get("chroot", ""))
    assert f"{chroot}/brokers/ids/0" in active_brokers
    assert f"{chroot}/brokers/ids/1" in active_brokers
    assert f"{chroot}/brokers/ids/2" not in active_brokers
