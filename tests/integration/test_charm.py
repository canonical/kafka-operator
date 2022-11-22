#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import time
from asyncio.subprocess import PIPE
from subprocess import check_output

import pytest
from client import KafkaClient
from pytest_operator.plugin import OpsTest

from literals import CHARM_KEY
from tests.integration.helpers import get_provider_data

logger = logging.getLogger(__name__)

DUMMY_NAME = "app"


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
    await ops_test.model.add_relation(CHARM_KEY, DUMMY_NAME)
    time.sleep(10)
    assert ops_test.model.applications[CHARM_KEY].status == "active"
    assert ops_test.model.applications[DUMMY_NAME].status == "active"

    # run action to enable producer
    action = await ops_test.model.units.get(f"{DUMMY_NAME}/0").run_action("make-admin")
    await action.wait()
    time.sleep(10)
    await ops_test.model.wait_for_idle(apps=[CHARM_KEY, DUMMY_NAME])
    assert ops_test.model.applications[CHARM_KEY].status == "active"
    assert ops_test.model.applications[DUMMY_NAME].status == "active"

    relation_data = get_provider_data(
        unit_name=f"{DUMMY_NAME}/0", model_full_name=ops_test.model_full_name
    )
    logger.debug(f"{relation_data=}")

    topic = "new-topic"
    username = relation_data.get("username", None)
    password = relation_data.get("password", None)
    servers = relation_data.get("uris", "").split(",")
    security_protocol = "SASL_PLAINTEXT"

    if not (username and password and servers):
        pytest.fail("missing relation data from app charm")

    client = KafkaClient(
        servers=servers,
        username=username,
        password=password,
        topic=topic,
        consumer_group_prefix=None,
        security_protocol=security_protocol,
    )

    client.create_topic()
    client.run_producer()

    logs = check_output(
        f"JUJU_MODEL={ops_test.model_full_name} juju ssh kafka/0 'find /var/snap/kafka/common/log-data'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    ).splitlines()

    logger.debug(f"{logs=}")

    passed = False
    for log in logs:
        if topic and "index" in log:
            passed = True

    assert passed, "logs not written to log directory"
