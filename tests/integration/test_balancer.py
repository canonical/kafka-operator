#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
from subprocess import CalledProcessError

import pytest
from pytest_operator.plugin import OpsTest

from .helpers import APP_NAME, ZK_NAME, balancer_is_running, balancer_is_secure

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.balancer


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, kafka_charm):
    await ops_test.model.add_machine(series="jammy")
    machine_ids = await ops_test.model.get_machines()
    await ops_test.model.create_storage_pool("test_pool", "lxd")

    await asyncio.gather(
        ops_test.model.deploy(
            kafka_charm,
            application_name=APP_NAME,
            num_units=2,
            series="jammy",
            to=machine_ids[0],
            storage={"data": {"pool": "test_pool", "size": 1024}},
            config={"roles": "broker,balancer"},
        ),
        ops_test.model.deploy(
            ZK_NAME, channel="edge", application_name=ZK_NAME, num_units=1, series="jammy"
        ),
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME], idle_period=30, timeout=3600)
    assert ops_test.model.applications[APP_NAME].status == "blocked"
    assert ops_test.model.applications[ZK_NAME].status == "active"


@pytest.mark.abort_on_fail
async def test_relate_not_enough_brokers(ops_test: OpsTest):
    await ops_test.model.add_relation(APP_NAME, ZK_NAME)
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME], idle_period=30)
    assert ops_test.model.applications[APP_NAME].status == "waiting"

    with pytest.raises(CalledProcessError):
        assert balancer_is_running(model_full_name=ops_test.model_full_name, app_name=APP_NAME)


@pytest.mark.abort_on_fail
async def test_minimum_brokers_balancer_starts(ops_test: OpsTest):
    await ops_test.model.applications[APP_NAME].add_units(count=2)
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[APP_NAME].units) == 4)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME], status="active", timeout=1800, idle_period=30
    )
    assert balancer_is_running(model_full_name=ops_test.model_full_name, app_name=APP_NAME)
    assert balancer_is_secure(ops_test, app_name=APP_NAME)


@pytest.mark.abort_on_fail
async def test_change_leader(ops_test: OpsTest):
    for unit in ops_test.model.applications[APP_NAME].units:
        if await unit.is_leader_from_status():
            leader_unit = unit

    await leader_unit.destroy(force=True, destroy_storage=True, max_wait=0)
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[APP_NAME].units) == 3)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=1800, idle_period=60
    )
    assert balancer_is_running(model_full_name=ops_test.model_full_name, app_name=APP_NAME)
    assert balancer_is_secure(ops_test, app_name=APP_NAME)
