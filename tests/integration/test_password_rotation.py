#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from pytest_operator.plugin import OpsTest

from .helpers import APP_NAME, SERIES, deploy_cluster, get_user, set_password

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker

DUMMY_NAME = "app"
REL_NAME_ADMIN = "kafka-client-admin"


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_build_and_deploy(ops_test: OpsTest, kraft_mode, kafka_charm, app_charm, kafka_apps):
    await asyncio.gather(
        deploy_cluster(
            ops_test=ops_test,
            charm=kafka_charm,
            kraft_mode=kraft_mode,
        ),
        ops_test.model.deploy(app_charm, application_name=DUMMY_NAME, num_units=1, series=SERIES),
    )
    await ops_test.model.wait_for_idle(
        apps=[*kafka_apps, DUMMY_NAME], timeout=2000, idle_period=30, raise_on_error=False
    )

    # needed to open localhost ports
    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")

    async with ops_test.fast_forward(fast_interval="30s"):
        await asyncio.sleep(90)

    await ops_test.model.wait_for_idle(
        apps=[*kafka_apps, DUMMY_NAME], status="active", idle_period=30, timeout=3600
    )


async def test_password_rotation(ops_test: OpsTest, kafka_apps):
    """Check that password stored on cluster has changed after a password rotation."""
    initial_sync_user = get_user(
        username="sync",
        model_full_name=ops_test.model_full_name,
    )

    result = await set_password(ops_test, username="sync", num_unit=0)
    assert "sync-password" in result.keys()

    await ops_test.model.wait_for_idle(apps=kafka_apps, status="active", idle_period=30)

    new_sync_user = get_user(
        username="sync",
        model_full_name=ops_test.model_full_name,
    )

    assert initial_sync_user != new_sync_user
