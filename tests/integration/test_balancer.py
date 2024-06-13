#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from pytest_operator.plugin import OpsTest

from literals import (
    BALANCER,
    BALANCER_RELATION,
    BALANCER_SERVICE,
)

from .helpers import (
    APP_NAME,
    ZK_NAME,
)

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.balancer


async def test_build_and_deploy(ops_test: OpsTest, kafka_charm):
    await ops_test.model.add_machine(series="jammy")
    machine_ids = await ops_test.model.get_machines()
    await ops_test.model.create_storage_pool("test_pool", "lxd")

    await asyncio.gather(
        ops_test.model.deploy(
            kafka_charm,
            application_name=APP_NAME,
            num_units=1,
            series="jammy",
            to=machine_ids[0],
            storage={"data": {"pool": "test_pool", "size": 1024}},
        ),
        ops_test.model.deploy(
            ZK_NAME, channel="edge", application_name=ZK_NAME, num_units=1, series="jammy"
        ),
        ops_test.model.deploy(
            kafka_charm, application_name=BALANCER.value, num_units=1, config={"role": "balancer"}
        ),
    )
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME, BALANCER.value], idle_period=30, timeout=3600
    )
    assert ops_test.model.applications[APP_NAME].status == "blocked"
    assert ops_test.model.applications[ZK_NAME].status == "active"
    assert ops_test.model.applications[BALANCER.value].status == "blocked"

    await ops_test.model.add_relation(APP_NAME, ZK_NAME)
    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, ZK_NAME], idle_period=30, status="active"
        )


@pytest.mark.abort_on_fail
async def test_can_relate_with_broker(ops_test: OpsTest):

    await ops_test.model.add_relation(
        f"{APP_NAME}:{BALANCER_RELATION}", f"{BALANCER.value}:{BALANCER_SERVICE}"
    )
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, BALANCER.value], idle_period=30, timeout=3600, status="active"
    )
