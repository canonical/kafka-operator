#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import time
from subprocess import PIPE, check_output
from typing import Dict

import pytest
import requests
from pytest_operator.plugin import OpsTest

from literals import JMX_EXPORTER_PORT, REL_NAME, SECURITY_PROTOCOL_PORTS

from .helpers import (
    APP_NAME,
    REL_NAME_ADMIN,
    ZK_NAME,
    check_socket,
    get_address,
    produce_and_check_logs,
    run_client_properties,
)

logger = logging.getLogger(__name__)

DUMMY_NAME = "app"
SAME_ZK = f"{ZK_NAME}-same"
SAME_KAFKA = f"{APP_NAME}-same"


@pytest.mark.abort_on_fail
async def test_build_and_deploy_same_machine(ops_test: OpsTest, kafka_charm):
    # deploying 1 machine
    await ops_test.model.add_machine(series="jammy")
    machine_ids = await ops_test.model.get_machines()

    # deploying both kafka + zk to same machine
    await asyncio.gather(
        ops_test.model.deploy(
            ZK_NAME,
            channel="edge",
            application_name=SAME_ZK,
            num_units=1,
            series="jammy",
            to=machine_ids[0],
        ),
        ops_test.model.deploy(
            kafka_charm,
            application_name=SAME_KAFKA,
            num_units=1,
            series="jammy",
            to=machine_ids[0],
        ),
    )
    await ops_test.model.wait_for_idle(apps=[SAME_ZK, SAME_KAFKA], idle_period=30, timeout=3600)
    assert ops_test.model.applications[SAME_KAFKA].status == "blocked"
    assert ops_test.model.applications[SAME_ZK].status == "active"

    await ops_test.model.add_relation(SAME_KAFKA, SAME_ZK)
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(apps=[SAME_ZK, SAME_KAFKA], idle_period=30)
        assert ops_test.model.applications[SAME_ZK].status == "active"
        assert ops_test.model.applications[SAME_KAFKA].status == "active"

    await asyncio.gather(
        ops_test.model.applications[SAME_KAFKA].remove(force=True, no_wait=True),
        ops_test.model.applications[SAME_ZK].remove(force=True, no_wait=True),
    )
    await ops_test.model.machines[machine_ids[0]].destroy()


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, kafka_charm):
    await ops_test.model.add_machine(series="jammy")
    machine_ids = await ops_test.model.get_machines()

    await asyncio.gather(
        ops_test.model.deploy(
            kafka_charm, application_name=APP_NAME, num_units=1, series="jammy", to=machine_ids[0]
        ),
        ops_test.model.deploy(
            ZK_NAME, channel="edge", application_name=ZK_NAME, num_units=1, series="jammy"
        ),
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME], idle_period=30, timeout=3600)
    assert ops_test.model.applications[APP_NAME].status == "blocked"
    assert ops_test.model.applications[ZK_NAME].status == "active"

    await ops_test.model.add_relation(APP_NAME, ZK_NAME)
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME], idle_period=30)
        assert ops_test.model.applications[APP_NAME].status == "active"
        assert ops_test.model.applications[ZK_NAME].status == "active"


@pytest.mark.abort_on_fail
async def test_listeners(ops_test: OpsTest, app_charm):
    address = await get_address(ops_test=ops_test)
    assert check_socket(
        address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT"].internal
    )  # Internal listener
    # Client listener should not be enabled if there is no relations
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
    # remove relation and check that client listener is not active
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

    acls = 0
    for line in result.strip().split("\n"):
        if "SCRAM credential configs for user-principal" in line:
            acls += 1
    assert acls == 3

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


async def test_rack_awareness_integration(ops_test: OpsTest):
    machine_ids = await ops_test.model.get_machines()
    await ops_test.model.deploy(
        "kafka-broker-rack-awareness",
        channel="edge",
        application_name="rack",
        to=machine_ids[0],
        series="jammy",
        config={"broker-rack": "integration-zone"},
    )
    await ops_test.model.wait_for_idle(apps=["rack"], idle_period=30, timeout=3600)
    assert ops_test.model.applications["rack"].status == "active"


async def test_exporter_endpoints(ops_test: OpsTest):
    unit_address = await get_address(ops_test=ops_test)
    jmx_exporter_url = f"http://{unit_address}:{JMX_EXPORTER_PORT}/metrics"
    jmx_resp = requests.get(jmx_exporter_url)
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


@pytest.mark.abort_on_fail
@pytest.mark.skip
async def test_observability_integration(ops_test: OpsTest):
    await ops_test.model.deploy(
        "ch:grafana-agent",
        channel="edge",
        application_name="agent",
        num_units=0,
        series="jammy",
    )

    await ops_test.model.add_relation(f"{APP_NAME}:cos-agent", "agent")

    # TODO uncomment once cos-agent is integrated in zookeeper
    # await ops_test.model.add_relation(f"{ZK_NAME}:juju-info", "agent")

    # Use the "idle_period" to have the scrape interval (60 sec) elapsed, to make sure all
    # "state" keys are updated from "unknown".
    await ops_test.model.wait_for_idle(status="active", idle_period=60)

    agent_units = ops_test.model.applications["agent"].units

    # Get all the "targets" from all grafana-agent units
    machine_targets: Dict[str, str] = {
        unit.machine.id: await unit.machine.ssh(
            "curl localhost:12345/agent/api/v1/metrics/targets"
        )
        for unit in agent_units
    }
    for targets in machine_targets.values():
        assert '"state":"up"' in targets
        assert '"state":"down"' not in targets
