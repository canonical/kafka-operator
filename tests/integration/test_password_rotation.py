#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from helpers import (
    APP_NAME,
    ZK_NAME,
    get_kafka_zk_relation_data,
    get_user,
    set_password,
)
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_build_and_deploy(ops_test: OpsTest):
    kafka_charm = await ops_test.build_charm(".")
    await asyncio.gather(
        ops_test.model.deploy(ZK_NAME, channel="edge", application_name=ZK_NAME, num_units=3),
        ops_test.model.deploy(kafka_charm, application_name=APP_NAME, num_units=1),
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


async def test_password_rotation(ops_test: OpsTest):
    """Check that password stored on ZK has changed after a password rotation."""
    relation_data = get_kafka_zk_relation_data(
        unit_name=f"{APP_NAME}/0", model_full_name=ops_test.model_full_name
    )
    uri = relation_data["uris"].split(",")[-1]

    initial_sync_user = get_user(
        username="sync",
        zookeeper_uri=uri,
        model_full_name=ops_test.model_full_name,
    )

    result = await set_password(ops_test, username="sync", num_unit=0)
    assert "sync-password" in result.keys()

    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME])

    new_sync_user = get_user(
        username="sync",
        zookeeper_uri=uri,
        model_full_name=ops_test.model_full_name,
    )

    assert initial_sync_user != new_sync_user
