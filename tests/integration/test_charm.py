#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import time
from subprocess import PIPE, check_output

import pytest
import requests

from literals import DEPENDENCIES, JMX_EXPORTER_PORT, REL_NAME, SECURITY_PROTOCOL_PORTS

from .adapters import JujuFixture, gather
from .helpers import (
    APP_NAME,
    DUMMY_NAME,
    REL_NAME_ADMIN,
    ZK_NAME,
    check_socket,
    count_lines_with,
    get_address,
    get_machine,
    produce_and_check_logs,
    run_client_properties,
)

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker

SAME_ZK = f"{ZK_NAME}-same"
SAME_KAFKA = f"{APP_NAME}-same"


# FIXME: https://github.com/canonical/kafka-operator/issues/142
@pytest.mark.skip
def test_build_and_deploy_same_machine(juju: JujuFixture, kafka_charm):
    # deploying 1 machine
    juju.ext.model.add_machine(series="jammy")
    machine_ids = juju.ext.model.get_machines()

    # deploying both kafka + zk to same machine
    gather(
        juju.ext.model.deploy(
            ZK_NAME,
            channel="edge",
            application_name=SAME_ZK,
            num_units=1,
            series="jammy",
            to=machine_ids[0],
        ),
        juju.ext.model.deploy(
            kafka_charm,
            application_name=SAME_KAFKA,
            num_units=1,
            series="jammy",
            to=machine_ids[0],
        ),
    )
    juju.ext.model.wait_for_idle(apps=[SAME_ZK, SAME_KAFKA], idle_period=30, timeout=1800)
    assert juju.ext.model.applications[SAME_ZK].status == "active"

    juju.ext.model.add_relation(SAME_KAFKA, SAME_ZK)

    juju.ext.model.wait_for_idle(
        apps=[SAME_KAFKA, SAME_ZK], idle_period=30, timeout=1800, status="active"
    )

    assert juju.ext.model.applications[SAME_ZK].status == "active"
    assert juju.ext.model.applications[SAME_KAFKA].status == "active"

    gather(
        juju.ext.model.applications[SAME_KAFKA].destroy(),
        juju.ext.model.applications[SAME_ZK].destroy(),
    )
    juju.ext.model.machines[machine_ids[0]].destroy()


def test_build_and_deploy(juju: JujuFixture, kafka_charm):
    juju.cli("create-storage-pool", "testing", "lxd")

    gather(
        juju.ext.model.deploy(
            kafka_charm,
            application_name=APP_NAME,
            num_units=1,
            base="ubuntu@22.04",
            storage={"data": "testing,1GiB"},
        ),
        juju.ext.model.deploy(
            ZK_NAME, channel="edge", application_name=ZK_NAME, num_units=1, series="jammy"
        ),
    )
    juju.ext.model.wait_for_idle(apps=[APP_NAME, ZK_NAME], idle_period=30, timeout=3600)
    assert juju.ext.model.applications[ZK_NAME].status == "active"

    juju.ext.model.add_relation(APP_NAME, ZK_NAME)
    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(apps=[APP_NAME, ZK_NAME], idle_period=30, status="active")


def test_consistency_between_workload_and_metadata(juju: JujuFixture):
    application = juju.status().apps[APP_NAME]
    assert application.version == DEPENDENCIES["kafka_service"]["version"]


def test_remove_zk_relation_relate(juju: JujuFixture):
    check_output(
        f"JUJU_MODEL={juju.ext.model_full_name} juju remove-relation {APP_NAME} {ZK_NAME}",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    juju.ext.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME], idle_period=40, timeout=3600, raise_on_error=False
    )

    juju.ext.model.add_relation(APP_NAME, ZK_NAME)

    with juju.ext.fast_forward(fast_interval="90s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, ZK_NAME],
            status="active",
            idle_period=30,
            timeout=1000,
            raise_on_error=False,
        )


def test_listeners(juju: JujuFixture, app_charm):
    address = get_address(juju=juju)
    assert check_socket(
        address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].internal
    )  # Internal listener

    # Client listener should not be enabled if there is no relations
    assert not check_socket(
        address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client
    )

    # Add relation with dummy app
    gather(
        juju.ext.model.deploy(app_charm, application_name=DUMMY_NAME, num_units=1, series="jammy"),
    )
    juju.ext.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME, ZK_NAME])

    juju.ext.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")

    assert juju.ext.model.applications[APP_NAME].status == "active"
    assert juju.ext.model.applications[DUMMY_NAME].status == "active"
    juju.ext.model.wait_for_idle(apps=[APP_NAME, ZK_NAME, DUMMY_NAME])

    # check that client listener is active
    assert check_socket(address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client)

    # remove relation and check that client listener is not active
    juju.ext.model.applications[APP_NAME].remove_relation(
        f"{APP_NAME}:{REL_NAME}", f"{DUMMY_NAME}:{REL_NAME_ADMIN}"
    )
    juju.ext.model.wait_for_idle(apps=[APP_NAME])

    assert not check_socket(
        address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client
    )


def test_client_properties_makes_admin_connection(juju: JujuFixture):
    juju.ext.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    assert juju.ext.model.applications[APP_NAME].status == "active"
    assert juju.ext.model.applications[DUMMY_NAME].status == "active"
    juju.ext.model.wait_for_idle(apps=[APP_NAME, ZK_NAME, DUMMY_NAME])
    result = run_client_properties(juju=juju)
    assert result

    acls = 0
    for line in result.strip().split("\n"):
        if "SCRAM credential configs for user-principal" in line:
            acls += 1
    assert acls == 3

    juju.ext.model.applications[APP_NAME].remove_relation(
        f"{APP_NAME}:{REL_NAME}", f"{DUMMY_NAME}:{REL_NAME_ADMIN}"
    )
    juju.ext.model.wait_for_idle(apps=[APP_NAME])


def test_logs_write_to_storage(juju: JujuFixture):
    juju.ext.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME])
    juju.ext.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    time.sleep(10)
    assert juju.ext.model.applications[APP_NAME].status == "active"
    assert juju.ext.model.applications[DUMMY_NAME].status == "active"
    juju.ext.model.wait_for_idle(apps=[APP_NAME, ZK_NAME, DUMMY_NAME], idle_period=30)

    produce_and_check_logs(
        juju=juju,
        kafka_unit_name=f"{APP_NAME}/0",
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="hot-topic",
    )


def test_rack_awareness_integration(juju: JujuFixture):
    kafka_machine_id = get_machine(juju)

    juju.ext.model.deploy(
        "kafka-broker-rack-awareness",
        channel="stable",
        application_name="rack",
        to=kafka_machine_id,
        config={"broker-rack": "integration-zone"},
    )
    juju.ext.model.wait_for_idle(apps=["rack"], idle_period=30, timeout=3600)
    assert juju.ext.model.applications["rack"].status == "active"


def test_exporter_endpoints(juju: JujuFixture):
    unit_address = get_address(juju=juju)
    jmx_exporter_url = f"http://{unit_address}:{JMX_EXPORTER_PORT}/metrics"
    jmx_resp = requests.get(jmx_exporter_url)
    assert jmx_resp.ok


def test_log_level_change(juju: JujuFixture):

    for unit in juju.ext.model.applications[APP_NAME].units:
        assert (
            count_lines_with(
                juju.ext.model_full_name,
                unit.name,
                "/var/snap/charmed-kafka/common/var/log/kafka/server.log",
                "DEBUG",
            )
            == 0
        )

    juju.ext.model.applications[APP_NAME].set_config({"log_level": "DEBUG"})

    juju.ext.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=1000, idle_period=30)

    for unit in juju.ext.model.applications[APP_NAME].units:
        assert (
            count_lines_with(
                juju.ext.model_full_name,
                unit.name,
                "/var/snap/charmed-kafka/common/var/log/kafka/server.log",
                "DEBUG",
            )
            > 0
        )

    juju.ext.model.applications[APP_NAME].set_config({"log_level": "INFO"})

    juju.ext.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=1000, idle_period=30)


@pytest.mark.skip  # skipping as we can't add storage without losing Juju conn
def test_logs_write_to_new_storage(juju: JujuFixture):
    check_output(
        f"JUJU_MODEL={juju.ext.model_full_name} juju add-storage kafka/0 log-data",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )
    time.sleep(5)  # to give time for storage to complete

    produce_and_check_logs(
        juju=juju,
        kafka_unit_name=f"{APP_NAME}/0",
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="cold-topic",
    )


@pytest.mark.skip
def test_observability_integration(juju: JujuFixture):
    juju.ext.model.deploy(
        "ch:grafana-agent",
        channel="edge",
        application_name="agent",
        num_units=0,
        series="jammy",
    )

    juju.ext.model.add_relation(f"{APP_NAME}:cos-agent", "agent")

    # TODO uncomment once cos-agent is integrated in zookeeper
    # juju.ext.model.add_relation(f"{ZK_NAME}:juju-info", "agent")

    # Use the "idle_period" to have the scrape interval (60 sec) elapsed, to make sure all
    # "state" keys are updated from "unknown".
    juju.ext.model.wait_for_idle(status="active", idle_period=60)

    agent_units = juju.ext.model.applications["agent"].units

    # Get all the "targets" from all grafana-agent units
    machine_targets: dict[str, str] = {
        unit.machine.id: unit.machine.ssh("curl localhost:12345/agent/api/v1/metrics/targets")
        for unit in agent_units
    }
    for targets in machine_targets.values():
        assert '"state":"up"' in targets
        assert '"state":"down"' not in targets


def test_deploy_with_existing_storage(juju: JujuFixture):
    unit_to_remove, *_ = juju.ext.model.applications[APP_NAME].add_units(count=1)
    juju.ext.model.block_until(lambda: len(juju.ext.model.applications[APP_NAME].units) == 2)
    juju.ext.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=2000, idle_period=30)

    _, stdout, _ = juju.old_cli("storage", "--format", "json")
    storages = json.loads(stdout)["storage"]

    for data_storage_id, content in storages.items():
        units = content["attachments"]["units"].keys()
        if unit_to_remove.name not in units:
            continue
        break

    unit_to_remove.remove(destroy_storage=False)
    juju.ext.model.block_until(lambda: len(juju.ext.model.applications[APP_NAME].units) == 1)

    add_unit_cmd = f"add-unit {APP_NAME} --model={juju.ext.model_full_name} --attach-storage={data_storage_id}".split()
    juju.old_cli(*add_unit_cmd)
    juju.ext.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=2000, idle_period=30, raise_on_error=False
    )
