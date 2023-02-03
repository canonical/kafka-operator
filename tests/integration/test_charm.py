#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import time
from pathlib import PosixPath
from subprocess import PIPE, check_output
from urllib import request

import pytest
from pytest_operator.plugin import OpsTest
from tests.integration.helpers import (
    APP_NAME,
    REL_NAME_ADMIN,
    ZK_NAME,
    check_socket,
    get_address,
    produce_and_check_logs,
    run_client_properties,
)

from literals import REL_NAME, SECURITY_PROTOCOL_PORTS

logger = logging.getLogger(__name__)

DUMMY_NAME = "app"


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    kafka_charm = await ops_test.build_charm(".")
    await asyncio.gather(
        ops_test.model.deploy(
            ZK_NAME, channel="edge", application_name=ZK_NAME, num_units=1, series="jammy"
        ),
        ops_test.model.deploy(kafka_charm, application_name=APP_NAME, num_units=1, series="jammy"),
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME])
    assert ops_test.model.applications[APP_NAME].status == "waiting"
    assert ops_test.model.applications[ZK_NAME].status == "active"

    await ops_test.model.add_relation(APP_NAME, ZK_NAME)
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME])
    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[ZK_NAME].status == "active"


@pytest.mark.abort_on_fail
async def test_listeners(ops_test: OpsTest, app_charm: PosixPath):
    address = await get_address(ops_test=ops_test)
    assert check_socket(
        address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT"].internal
    )  # Internal listener
    # Client listener should not be enable if there is no relations
    assert not check_socket(address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT"].client)
    # Add relation with dummy app
    await asyncio.gather(
        ops_test.model.deploy(app_charm, application_name=DUMMY_NAME, num_units=1, series="jammy"),
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME, ZK_NAME])
    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[DUMMY_NAME].status == "active"
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME, DUMMY_NAME])
    # check that client listener is active
    assert check_socket(address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT"].client)
    # remove relation and check that client listerner is not active
    await ops_test.model.applications[APP_NAME].remove_relation(
        f"{APP_NAME}:{REL_NAME}", f"{DUMMY_NAME}:{REL_NAME_ADMIN}"
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME])
    assert not check_socket(address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT"].client)


@pytest.mark.abort_on_fail
async def test_client_properties_makes_admin_connection(ops_test: OpsTest):
    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[DUMMY_NAME].status == "active"
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME, DUMMY_NAME])
    result = await run_client_properties(ops_test=ops_test)
    assert result
    assert len(result.strip().split("\n")) == 3
    await ops_test.model.applications[APP_NAME].remove_relation(
        f"{APP_NAME}:{REL_NAME}", f"{DUMMY_NAME}:{REL_NAME_ADMIN}"
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME])


@pytest.mark.abort_on_fail
async def test_logs_write_to_storage(ops_test: OpsTest):
    await ops_test.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME])
    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    time.sleep(10)
    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[DUMMY_NAME].status == "active"
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME, DUMMY_NAME])
    produce_and_check_logs(
        model_full_name=ops_test.model_full_name,
        kafka_unit_name=f"{APP_NAME}/0",
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="hot-topic",
    )


async def test_exporter_endpoints(ops_test: OpsTest):
    unit_address = await get_address(ops_test=ops_test)
    node_exporter_url = f"http://{unit_address}:9100/metrics"
    jmx_exporter_url = f"http://{unit_address}:9101/metrics"

    node_resp = request.get(node_exporter_url)
    jmx_resp = request.get(jmx_exporter_url)

    assert node_resp.ok
    assert jmx_resp.ok


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
        kafka_unit_name=f"{APP_NAME}/0",
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="cold-topic",
    )
