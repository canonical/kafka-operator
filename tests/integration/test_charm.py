#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import time
from subprocess import PIPE, check_output

import pytest
from literals import CHARM_KEY
from pytest_operator.plugin import OpsTest

from tests.integration.helpers import produce_and_check_logs

logger = logging.getLogger(__name__)

DUMMY_NAME = "app"
REL_NAME = "kafka-client-admin"


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    kafka_charm = await ops_test.build_charm(".")
    await asyncio.gather(
        ops_test.model.deploy(
            "zookeeper", channel="edge", application_name="zookeeper", num_units=1, series="focal"
        ),
        ops_test.model.deploy(kafka_charm, application_name="kafka", num_units=1, series="jammy"),
    )
    await ops_test.model.wait_for_idle(apps=["kafka", "zookeeper"])
    assert ops_test.model.applications["kafka"].status == "waiting"
    assert ops_test.model.applications["zookeeper"].status == "active"

    await ops_test.model.add_relation("kafka", "zookeeper")
    await ops_test.model.wait_for_idle(apps=["kafka", "zookeeper"])
    assert ops_test.model.applications["kafka"].status == "active"
    assert ops_test.model.applications["zookeeper"].status == "active"


@pytest.mark.abort_on_fail
async def test_logs_write_to_storage(ops_test: OpsTest):
    app_charm = await ops_test.build_charm("tests/integration/app-charm")
    await asyncio.gather(
        ops_test.model.deploy(app_charm, application_name=DUMMY_NAME, num_units=1, series="jammy"),
    )
    await ops_test.model.wait_for_idle(apps=[CHARM_KEY, DUMMY_NAME])
    await ops_test.model.add_relation(CHARM_KEY, f"{DUMMY_NAME}:{REL_NAME}")
    time.sleep(10)
    assert ops_test.model.applications[CHARM_KEY].status == "active"
    assert ops_test.model.applications[DUMMY_NAME].status == "active"
    await ops_test.model.wait_for_idle(apps=["kafka", "zookeeper", DUMMY_NAME])
    produce_and_check_logs(
        model_full_name=ops_test.model_full_name,
        kafka_unit_name="kafka/0",
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="hot-topic",
    )


@pytest.mark.abort_on_fail
@pytest.mark.skip  # skipping as we can't add storage without losing Juju conn
async def test_logs_write_to_new_storage(ops_test: OpsTest):
    check_output(
        f"JUJU_MODEL={ops_test.model_full_name} juju add-storage kafka/0 log-data",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )
    time.sleep(5)  # to give time for storage to complete

    produce_and_check_logs(
        model_full_name=ops_test.model_full_name,
        kafka_unit_name="kafka/0",
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="cold-topic",
    )
