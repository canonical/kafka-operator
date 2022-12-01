#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from helpers import (
    APP_NAME,
    ZK_NAME,
    set_rack_id,
    get_rack_id
)
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_build_and_deploy(ops_test: OpsTest):
    kafka_charm = await ops_test.build_charm(".")
    await asyncio.gather(
        ops_test.model.deploy(
            ZK_NAME, channel="edge", application_name=ZK_NAME, num_units=3, series="focal"
        ),
        ops_test.model.deploy(kafka_charm, application_name=APP_NAME, num_units=1, series="jammy"),
    )
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[ZK_NAME].units) == 3)
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME])
    assert ops_test.model.applications[APP_NAME].status == "waiting"
    assert ops_test.model.applications[ZK_NAME].status == "active"

    await ops_test.model.add_relation(APP_NAME, ZK_NAME)

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME])

    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[ZK_NAME].status == "active"


async def test_rack_awereness(ops_test: OpsTest):
    """Check that rack-id has changed after running the set-rack-id action."""
    first_rack_id = get_rack_id(ops_test.model_full_name)

    assert first_rack_id is None

    result = await set_rack_id(ops_test, num_unit=0, rack_id="my-rack-id")

    assert result == "my-rack-id"

    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME])

    second_rack_id = get_rack_id(ops_test.model_full_name)

    assert second_rack_id == "my-rack-id"
