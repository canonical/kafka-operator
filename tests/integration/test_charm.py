#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import json
import logging
import time
from subprocess import PIPE, check_output

import pytest
import requests
from pytest_operator.plugin import OpsTest

from literals import (
    DEPENDENCIES,
    JMX_EXPORTER_PORT,
    PEER_CLUSTER_ORCHESTRATOR_RELATION,
    PEER_CLUSTER_RELATION,
    REL_NAME,
    SECURITY_PROTOCOL_PORTS,
)

from .helpers import (
    APP_NAME,
    DUMMY_NAME,
    REL_NAME_ADMIN,
    SERIES,
    check_socket,
    count_lines_with,
    deploy_cluster,
    get_address,
    get_machine,
    produce_and_check_logs,
    run_client_properties,
)

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_build_and_deploy(ops_test: OpsTest, kafka_charm, kraft_mode, controller_app):
    await ops_test.model.create_storage_pool("test_pool", "lxd")

    await deploy_cluster(
        ops_test=ops_test,
        charm=kafka_charm,
        kraft_mode=kraft_mode,
        storage_broker={"data": {"pool": "test_pool", "size": 1024}},
    )
    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[controller_app].status == "active"


@pytest.mark.abort_on_fail
async def test_consistency_between_workload_and_metadata(ops_test: OpsTest):
    application = ops_test.model.applications[APP_NAME]
    assert application.data.get("workload-version", "") == DEPENDENCIES["kafka_service"]["version"]


@pytest.mark.abort_on_fail
async def test_remove_controller_relation_relate(ops_test: OpsTest, kraft_mode, controller_app):
    if kraft_mode == "single":
        logger.info(f"Skipping because we're using {kraft_mode} mode.")
        return

    check_output(
        f"JUJU_MODEL={ops_test.model_full_name} juju remove-relation {APP_NAME} {controller_app}",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, controller_app], idle_period=40, timeout=3600, raise_on_error=False
    )

    await ops_test.model.add_relation(
        f"{APP_NAME}:{PEER_CLUSTER_ORCHESTRATOR_RELATION}",
        f"{controller_app}:{PEER_CLUSTER_RELATION}",
    )

    async with ops_test.fast_forward(fast_interval="90s"):
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, controller_app],
            status="active",
            idle_period=30,
            timeout=1000,
            raise_on_error=False,
        )


@pytest.mark.abort_on_fail
async def test_listeners(ops_test: OpsTest, app_charm, kafka_apps):
    address = await get_address(ops_test=ops_test)
    assert check_socket(
        address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].internal
    )  # Internal listener

    # Client listener should not be enabled if there is no relations
    assert not check_socket(
        address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client
    )

    # Add relation with dummy app
    await asyncio.gather(
        ops_test.model.deploy(app_charm, application_name=DUMMY_NAME, num_units=1, series=SERIES),
    )
    await ops_test.model.wait_for_idle(apps=[*kafka_apps, DUMMY_NAME])

    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")

    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[DUMMY_NAME].status == "active"
    await ops_test.model.wait_for_idle(
        apps=[*kafka_apps, DUMMY_NAME], idle_period=60, status="active"
    )

    # check that client listener is active
    assert check_socket(address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client)

    # remove relation and check that client listener is not active
    await ops_test.model.applications[APP_NAME].remove_relation(
        f"{APP_NAME}:{REL_NAME}", f"{DUMMY_NAME}:{REL_NAME_ADMIN}"
    )
    await ops_test.model.wait_for_idle(apps=[*kafka_apps])

    assert not check_socket(
        address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client
    )


@pytest.mark.abort_on_fail
async def test_client_properties_makes_admin_connection(ops_test: OpsTest, kafka_apps, kraft_mode):
    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[DUMMY_NAME].status == "active"
    await ops_test.model.wait_for_idle(
        apps=[*kafka_apps, DUMMY_NAME], idle_period=60, status="active"
    )
    result = await run_client_properties(ops_test=ops_test)
    assert result
    print(result)

    acls = 0
    for line in result.strip().split("\n"):
        if "SCRAM credential configs for user-principal" in line:
            acls += 1

    # single mode: admin, sync, relation-# => 3
    # multi mode: admin, relation-# => 2
    assert acls == 2 + int(kraft_mode == "single")

    await ops_test.model.applications[APP_NAME].remove_relation(
        f"{APP_NAME}:{REL_NAME}", f"{DUMMY_NAME}:{REL_NAME_ADMIN}"
    )
    await ops_test.model.wait_for_idle(apps=kafka_apps)


@pytest.mark.abort_on_fail
async def test_logs_write_to_storage(ops_test: OpsTest, kafka_apps):
    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    await ops_test.model.wait_for_idle(
        apps=[*kafka_apps, DUMMY_NAME], idle_period=60, status="active"
    )

    produce_and_check_logs(
        ops_test=ops_test,
        kafka_unit_name=f"{APP_NAME}/0",
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="warm-topic",
    )


@pytest.mark.skip(reason="can't test with locally built snap")
async def test_rack_awareness_integration(ops_test: OpsTest):
    kafka_machine_id = await get_machine(ops_test)

    await ops_test.model.deploy(
        "kafka-broker-rack-awareness",
        channel="edge",
        application_name="rack",
        base="ubuntu@22.04",
        to=kafka_machine_id,
        config={"broker-rack": "integration-zone"},
    )
    await ops_test.model.wait_for_idle(apps=["rack"], idle_period=30, timeout=3600)
    assert ops_test.model.applications["rack"].status == "active"


@pytest.mark.abort_on_fail
async def test_exporter_endpoints(ops_test: OpsTest):
    unit_address = await get_address(ops_test=ops_test)
    jmx_exporter_url = f"http://{unit_address}:{JMX_EXPORTER_PORT}/metrics"
    jmx_resp = requests.get(jmx_exporter_url)
    assert jmx_resp.ok


@pytest.mark.abort_on_fail
async def test_log_level_change(ops_test: OpsTest, kafka_apps):

    for unit in ops_test.model.applications[APP_NAME].units:
        assert (
            count_lines_with(
                ops_test.model_full_name,
                unit.name,
                "/var/snap/charmed-kafka/common/var/log/kafka/server.log",
                "DEBUG",
            )
            == 0
        )

    await ops_test.model.applications[APP_NAME].set_config({"log_level": "DEBUG"})

    await ops_test.model.wait_for_idle(
        apps=kafka_apps, status="active", timeout=1000, idle_period=30
    )

    for unit in ops_test.model.applications[APP_NAME].units:
        assert (
            count_lines_with(
                ops_test.model_full_name,
                unit.name,
                "/var/snap/charmed-kafka/common/var/log/kafka/server.log",
                "DEBUG",
            )
            > 0
        )

    await ops_test.model.applications[APP_NAME].set_config({"log_level": "INFO"})

    await ops_test.model.wait_for_idle(
        apps=kafka_apps, status="active", timeout=1000, idle_period=30
    )


@pytest.mark.abort_on_fail
@pytest.mark.skip(reason="skipping as we can't add storage without losing Juju conn")
async def test_logs_write_to_new_storage(ops_test: OpsTest):
    check_output(
        f"JUJU_MODEL={ops_test.model_full_name} juju add-storage kafka/0 log-data",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )
    time.sleep(5)  # to give time for storage to complete

    produce_and_check_logs(
        ops_test=ops_test,
        kafka_unit_name=f"{APP_NAME}/0",
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="cold-topic",
    )


@pytest.mark.abort_on_fail
@pytest.mark.fails_in_kafka4
@pytest.mark.skip(reason="storage format command fails in KRaft mode")
async def test_deploy_with_existing_storage(ops_test: OpsTest, kafka_apps):
    unit_to_remove, *_ = await ops_test.model.applications[APP_NAME].add_units(count=1)
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[APP_NAME].units) == 2)
    await ops_test.model.wait_for_idle(
        apps=kafka_apps, status="active", timeout=2000, idle_period=30
    )

    _, stdout, _ = await ops_test.juju("storage", "--format", "json")
    storages = json.loads(stdout)["storage"]

    for data_storage_id, content in storages.items():
        units = content["attachments"]["units"].keys()
        if unit_to_remove.name not in units:
            continue
        break

    await unit_to_remove.remove(destroy_storage=False)
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[APP_NAME].units) == 1)

    add_unit_cmd = f"add-unit {APP_NAME} --model={ops_test.model.info.name} --attach-storage={data_storage_id}".split()
    await ops_test.juju(*add_unit_cmd)
    await ops_test.model.wait_for_idle(
        apps=kafka_apps, status="active", timeout=2000, idle_period=30, raise_on_error=False
    )
