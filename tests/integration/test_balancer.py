#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from pytest_operator.plugin import OpsTest

from literals import (
    BALANCER,
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
            num_units=3,
            series="jammy",
            to=machine_ids[0],
            storage={"data": {"pool": "test_pool", "size": 1024}},
            config={"roles": "broker,balancer"},
        ),
        ops_test.model.deploy(
            ZK_NAME, channel="edge", application_name=ZK_NAME, num_units=1, series="jammy"
        ),
    )
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME, BALANCER.value], idle_period=30, timeout=3600
    )
    assert ops_test.model.applications[APP_NAME].status == "blocked"
    assert ops_test.model.applications[ZK_NAME].status == "active"

    await ops_test.model.add_relation(APP_NAME, ZK_NAME)
    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, ZK_NAME], idle_period=30, status="active"
        )
