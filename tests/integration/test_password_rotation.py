#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from pytest_operator.plugin import OpsTest

from .helpers import APP_NAME, ZK_NAME, get_user, set_password

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker

DUMMY_NAME = "app"
REL_NAME_ADMIN = "kafka-client-admin"


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_build_and_deploy(ops_test: OpsTest, kafka_charm, app_charm):
    await asyncio.gather(
        ops_test.model.deploy(
            ZK_NAME, channel="edge", application_name=ZK_NAME, num_units=3, series="jammy"
        ),
        ops_test.model.deploy(
            kafka_charm,
            application_name=APP_NAME,
            num_units=1,
            series="jammy",
            storage={"data": ",,1"},
        ),
        ops_test.model.deploy(app_charm, application_name=DUMMY_NAME, num_units=1, series="jammy"),
    )
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[ZK_NAME].units) == 3)
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME])
    assert ops_test.model.applications[APP_NAME].status == "blocked"
    assert ops_test.model.applications[ZK_NAME].status == "active"

    # needed to open localhost ports
    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    await ops_test.model.add_relation(APP_NAME, ZK_NAME)

    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME], status="active", idle_period=30)


async def test_password_rotation(ops_test: OpsTest):
    """Check that password stored on ZK has changed after a password rotation."""
    initial_sync_user = get_user(
        model_full_name=ops_test.model_full_name,
    )

    result = await set_password(ops_test, username="sync", num_unit=0)
    assert "sync-password" in result.keys()

    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME], status="active", idle_period=30)

    new_sync_user = get_user(
        model_full_name=ops_test.model_full_name,
    )

    assert initial_sync_user != new_sync_user
