#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    kafka_charm = await ops_test.build_charm(".")
    await asyncio.gather(
        ops_test.model.deploy(
            "zookeeper", channel="edge", application_name="zookeeper", num_units=1
        ),
        ops_test.model.deploy(kafka_charm, application_name="kafka", num_units=1),
    )
    await ops_test.model.wait_for_idle(apps=["kafka", "zookeeper"])
    assert ops_test.model.applications["kafka"].status == "waiting"
    assert ops_test.model.applications["zookeeper"].status == "active"

    await ops_test.model.add_relation("kafka", "zookeeper")
    await ops_test.model.wait_for_idle(apps=["kafka", "zookeeper"])
    assert ops_test.model.applications["kafka"].status == "active"
    assert ops_test.model.applications["zookeeper"].status == "active"
