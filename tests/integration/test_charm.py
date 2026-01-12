#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import re
import subprocess
import time
from subprocess import PIPE, check_output

import jubilant
import pytest
import requests
import toml

from integration.helpers import APP_NAME, DUMMY_NAME, REL_NAME_ADMIN
from integration.helpers.jubilant import (
    BASE,
    all_active_idle,
    check_socket,
    count_lines_with,
    deploy_cluster,
    get_address,
    get_machine,
    produce_and_check_logs,
    run_client_properties,
)
from literals import (
    JMX_EXPORTER_PORT,
    PATHS,
    PEER_CLUSTER_ORCHESTRATOR_RELATION,
    PEER_CLUSTER_RELATION,
    REL_NAME,
    SECURITY_PROTOCOL_PORTS,
)

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker


def test_build_and_deploy(juju: jubilant.Juju, kafka_charm, kraft_mode, controller_app):
    juju.cli("create-storage-pool", "test_pool", "lxd")

    deploy_cluster(
        juju=juju,
        charm=kafka_charm,
        kraft_mode=kraft_mode,
        storage_broker={"data": "lxd,1G"},
    )

    juju.wait(
        lambda status: all_active_idle(status, APP_NAME, controller_app),
        delay=3,
        successes=20,
        timeout=900,
    )


def test_consistency_between_workload_and_metadata(juju: jubilant.Juju):
    with open("refresh_versions.toml", "r") as f:
        data = toml.load(f)
    assert juju.status().apps[APP_NAME].version == data["workload"]


def test_remove_controller_relation_relate(juju: jubilant.Juju, kraft_mode, controller_app):
    if kraft_mode == "single":
        logger.info(f"Skipping because we're using {kraft_mode} mode.")
        return

    juju.remove_relation(APP_NAME, controller_app)

    juju.wait(
        lambda status: jubilant.all_agents_idle(status, APP_NAME, controller_app)
        and jubilant.all_blocked(status, APP_NAME, controller_app),
        delay=3,
        successes=15,
        timeout=3600,
    )

    juju.integrate(
        f"{APP_NAME}:{PEER_CLUSTER_ORCHESTRATOR_RELATION}",
        f"{controller_app}:{PEER_CLUSTER_RELATION}",
    )

    juju.wait(
        lambda status: all_active_idle(status, APP_NAME, controller_app),
        delay=3,
        successes=10,
        timeout=1000,
    )


def test_listeners(juju: jubilant.Juju, app_charm, kafka_apps):
    address = get_address(juju=juju)
    assert check_socket(
        address, SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].internal
    )  # Internal listener

    # Client listener should not be enabled if there is no relations
    assert not check_socket(
        address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client
    )

    # Add relation with dummy app
    juju.deploy(app_charm, app=DUMMY_NAME, num_units=1)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=600,
    )

    juju.integrate(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=20,
        timeout=600,
    )

    # check that client listener is active
    assert check_socket(address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client)

    # remove relation and check that client listener is not active
    juju.remove_relation(f"{APP_NAME}:{REL_NAME}", f"{DUMMY_NAME}:{REL_NAME_ADMIN}")

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=20,
        timeout=600,
    )

    assert not check_socket(
        address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client
    )


def test_client_properties_makes_admin_connection(juju: jubilant.Juju, kafka_apps, kraft_mode):
    juju.integrate(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=20,
        timeout=600,
    )

    result = run_client_properties(juju=juju)
    assert result
    logger.debug(f"{result=}")

    acls = 0
    for line in result.strip().split("\n"):
        if "SCRAM credential configs for user-principal" in line:
            acls += 1

    # single mode: operator, replication, relation-# => 3
    # multi mode: operator, relation-# => 2
    assert acls == 2 + int(kraft_mode == "single")

    juju.remove_relation(f"{APP_NAME}:{REL_NAME}", f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=20,
        timeout=600,
    )


def test_logs_write_to_storage(juju: jubilant.Juju, kafka_apps):
    juju.integrate(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=20,
        timeout=600,
    )

    produce_and_check_logs(
        juju=juju,
        kafka_unit_name=f"{APP_NAME}/0",
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="warm-topic",
    )


def test_rack_awareness_integration(juju: jubilant.Juju):
    kafka_machine_id = get_machine(juju)

    juju.deploy(
        "kafka-broker-rack-awareness",
        channel="edge",
        app="rack",
        base=BASE,
        to=kafka_machine_id,
        config={"broker-rack": "integration-zone"},
    )

    juju.wait(
        lambda status: all_active_idle(status, "rack"),
        delay=3,
        successes=20,
        timeout=600,
    )


def test_exporter_endpoints(juju: jubilant.Juju):
    unit_address = get_address(juju=juju)
    jmx_exporter_url = f"http://{unit_address}:{JMX_EXPORTER_PORT}/metrics"
    jmx_resp = requests.get(jmx_exporter_url)
    assert jmx_resp.ok


def test_auxiliary_paths(juju: jubilant.Juju):
    for path in PATHS["kafka"]:
        result = subprocess.check_output(
            f"JUJU_MODEL={juju.model} juju ssh {APP_NAME}/leader sudo ls -l \\${path}",
            shell=True,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        print(f"{path} content: {result}")
        match = re.match("total ([0-9]+)", result)
        assert match
        # Some files should be there.
        assert int(match.group(1)) > 0


def test_log_level_change(juju: jubilant.Juju, kafka_apps):
    status = juju.status()
    for unit in status.apps[APP_NAME].units:
        assert (
            count_lines_with(
                juju.model,
                unit,
                "/var/snap/charmed-kafka/common/var/log/kafka/server.log",
                "DEBUG",
            )
            == 0
        )

    juju.config(APP_NAME, {"log-level": "DEBUG"})

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=3,
        successes=10,
        timeout=900,
    )

    for unit in status.apps[APP_NAME].units:
        assert (
            count_lines_with(
                juju.model,
                unit,
                "/var/snap/charmed-kafka/common/var/log/kafka/server.log",
                "DEBUG",
            )
            > 0
        )

    juju.config(APP_NAME, {"log-level": "INFO"})

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=3,
        successes=10,
        timeout=900,
    )


@pytest.mark.skip(reason="skipping as we can't add storage without losing Juju conn")
def test_logs_write_to_new_storage(juju: jubilant.Juju):
    check_output(
        f"JUJU_MODEL={juju.model} juju add-storage kafka/0 log-data",
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


@pytest.mark.fails_in_kafka4
@pytest.mark.skip(reason="storage format command fails in KRaft mode")
def test_deploy_with_existing_storage(juju: jubilant.Juju, kafka_apps):
    unit_to_remove, *_ = juju.model.applications[APP_NAME].add_units(count=1)
    juju.model.block_until(lambda: len(juju.model.applications[APP_NAME].units) == 2)
    juju.model.wait_for_idle(apps=kafka_apps, status="active", timeout=2000, idle_period=30)

    _, stdout, _ = juju.juju("storage", "--format", "json")
    storages = json.loads(stdout)["storage"]

    for data_storage_id, content in storages.items():
        units = content["attachments"]["units"].keys()
        if unit_to_remove.name not in units:
            continue
        break

    unit_to_remove.remove(destroy_storage=False)
    juju.model.block_until(lambda: len(juju.model.applications[APP_NAME].units) == 1)

    add_unit_cmd = f"add-unit {APP_NAME} --model={juju.model.info.name} --attach-storage={data_storage_id}".split()
    juju.juju(*add_unit_cmd)
    juju.model.wait_for_idle(
        apps=kafka_apps, status="active", timeout=2000, idle_period=30, raise_on_error=False
    )
