#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import time

import pytest
from pytest_operator.plugin import OpsTest

from .helpers import APP_NAME, ZK_NAME

# FIXME: update this to 'stable' when `pre-upgrade-check` is released to 'stable'
CHANNEL = "edge"


@pytest.mark.abort_on_fail
async def test_in_place_upgrade(ops_test: OpsTest, kafka_charm):
    await asyncio.gather(
        ops_test.model.deploy(
            ZK_NAME,
            channel="edge",
            application_name=ZK_NAME,
            num_units=1,
            series="jammy",
        ),
        ops_test.model.deploy(
            APP_NAME,
            application_name=APP_NAME,
            num_units=3,
            channel=CHANNEL,
            series="jammy",
        ),
    )

    await ops_test.model.add_relation(APP_NAME, ZK_NAME)
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME], idle_period=30)
        assert ops_test.model.applications[APP_NAME].status == "active"
        assert ops_test.model.applications[ZK_NAME].status == "active"

    leader_unit = None
    for unit in ops_test.model.applications[APP_NAME].units:
        if await unit.is_leader_from_status():
            leader_unit = unit
    assert leader_unit

    action = await leader_unit.run_action("pre-upgrade-check")
    await action.wait()

    # ensure action completes
    time.sleep(10)

    await ops_test.model.applications[APP_NAME].refresh(path=kafka_charm)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=1000, idle_period=120
    )
