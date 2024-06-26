#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
from subprocess import PIPE, CalledProcessError, check_output

import pytest
from pytest_operator.plugin import OpsTest

from .helpers import (
    APP_NAME,
    ZK_NAME,
)

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.balancer


def is_balancer_running(model_full_name: str | None) -> bool:
    try:
        check_output(
            f"JUJU_MODEL={model_full_name} juju ssh kafka/0 sudo -i 'curl http://localhost:9090/kafkacruisecontrol/state'",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )
    except CalledProcessError:
        return False
    return True


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


async def test_relate_not_enough_brokers(ops_test: OpsTest):
    await ops_test.model.add_relation(APP_NAME, ZK_NAME)
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME], idle_period=30, status="active")
    assert not is_balancer_running(model_full_name=ops_test.model_full_name)


async def test_minimum_brokers_balancer_starts(ops_test: OpsTest):
    await ops_test.model.applications[APP_NAME].add_units(count=1)
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME], idle_period=30, status="active")
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[APP_NAME].units) == 3)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=1000, idle_period=30
    )
    assert is_balancer_running(model_full_name=ops_test.model_full_name)
