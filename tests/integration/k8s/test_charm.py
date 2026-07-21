#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time
from subprocess import PIPE, check_output

import jubilant
import pytest
import requests
import toml
from single_kernel_kafka.core.literals import (
    PEER_CLUSTER_ORCHESTRATOR_RELATION,
    PEER_CLUSTER_RELATION,
    REL_NAME,
    SECURITY_PROTOCOL_PORTS,
)

from integration.k8s.helpers.jubilant import all_active_idle, deploy_cluster, fast_forward
from integration.k8s.helpers.legacy import (
    APP_NAME,
    DUMMY_NAME,
    REL_NAME_ADMIN,
    check_external_access_non_tls,
    check_logs,
    count_lines_with,
    get_address,
    netcat,
    run_client_properties,
    wait_for_relation_removed_between,
)

logger = logging.getLogger(__name__)


def test_build_and_deploy(juju: jubilant.Juju, kafka_charm, kraft_mode, controller_app):
    deploy_cluster(
        juju=juju,
        charm=kafka_charm,
        kraft_mode=kraft_mode,
        config_broker={"expose-external": "nodeport"},
    )

    status = juju.status()
    assert status.apps[APP_NAME].app_status.current == "active"
    assert status.apps[controller_app].app_status.current == "active"


def test_consistency_between_workload_and_metadata(juju: jubilant.Juju):
    application = juju.status().apps[APP_NAME]
    with open("k8s/refresh_versions.toml", "r") as f:
        data = toml.load(f)
    assert application.version == data["workload"]


def test_remove_controller_relation_relate(juju: jubilant.Juju, kraft_mode, controller_app):
    if kraft_mode == "single":
        logger.info(f"Skipping because we're using {kraft_mode} mode.")
        return

    check_output(
        f"JUJU_MODEL={juju.model} juju remove-relation {APP_NAME} {controller_app}",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    juju.wait(
        lambda status: jubilant.all_agents_idle(status, APP_NAME, controller_app),
        delay=2,
        successes=20,
    )

    juju.integrate(
        f"{APP_NAME}:{PEER_CLUSTER_ORCHESTRATOR_RELATION}",
        f"{controller_app}:{PEER_CLUSTER_RELATION}",
    )

    with fast_forward(juju, fast_interval="90s"):
        juju.wait(
            lambda status: all_active_idle(status, APP_NAME, controller_app),
            delay=3,
            successes=10,
            timeout=1000,
        )


def test_listeners(juju: jubilant.Juju, app_charm, kafka_apps):
    address = get_address(juju=juju)
    assert netcat(
        address, SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].internal
    )  # Internal listener
    # Client listener should not be enable if there is no relations
    assert not netcat(address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client)

    # Add relation with dummy app
    juju.deploy(app_charm, app=DUMMY_NAME, num_units=1, base="ubuntu@22.04", trust=True)
    juju.integrate(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")

    with fast_forward(juju, fast_interval="120s"):
        juju.wait(
            lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
            delay=3,
            successes=10,
            timeout=2000,
        )

    # check that client listener is active
    assert netcat(address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client)

    # remove relation and check that client listener is not active
    juju.remove_relation(f"{APP_NAME}:{REL_NAME}", f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps), delay=2, successes=30, timeout=600
    )

    wait_for_relation_removed_between(juju, REL_NAME, REL_NAME_ADMIN)

    assert not netcat(address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client)


def test_client_properties_makes_admin_connection(juju: jubilant.Juju, kafka_apps, kraft_mode):
    juju.integrate(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")

    with fast_forward(juju, fast_interval="120s"):
        juju.wait(
            lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
            delay=2,
            successes=20,
            timeout=900,
        )

    result = run_client_properties(juju=juju)
    assert result
    # Check if relation-# exists in the result
    assert "relation-" in result, "Expected 'relation-' substring not found in result"

    juju.remove_relation(f"{APP_NAME}:{REL_NAME}", f"{DUMMY_NAME}:{REL_NAME_ADMIN}")

    with fast_forward(juju, fast_interval="20s"):
        time.sleep(120)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps), delay=2, successes=20, timeout=600
    )

    wait_for_relation_removed_between(juju, REL_NAME, REL_NAME_ADMIN)


def test_logs_write_to_storage(juju: jubilant.Juju, kafka_apps):
    juju.integrate(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")

    with fast_forward(juju, fast_interval="120s"):
        juju.wait(
            lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
            delay=2,
            successes=20,
            timeout=800,
        )

    juju.run(f"{DUMMY_NAME}/0", "produce")

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=2,
        successes=15,
        timeout=1000,
    )

    check_logs(
        juju=juju,
        kafka_unit_name=f"{APP_NAME}/0",
        topic="test-topic",
    )


def test_external_listeners_bootstrap(juju: jubilant.Juju):
    check_external_access_non_tls(juju, f"{APP_NAME}/0")


def test_exporter_endpoints(juju: jubilant.Juju):
    unit_address = get_address(juju=juju)
    jmx_exporter_url = f"http://{unit_address}:9101/metrics"
    jmx_resp = requests.get(jmx_exporter_url)

    assert jmx_resp.ok


@pytest.mark.skip(reason="No feature yet, needs newer image")
def test_log_level_change(juju: jubilant.Juju):
    for unit in juju.status().apps[APP_NAME].units:
        total_lines = count_lines_with(
            juju,
            unit,
            "/var/log/kafka/server.log",
            "DEBUG",
        )
        assert total_lines == 0

    juju.config(APP_NAME, {"log-level": "DEBUG"})
    juju.wait(
        lambda status: all_active_idle(status, APP_NAME), delay=2, successes=15, timeout=1000
    )

    for unit in juju.status().apps[APP_NAME].units:
        total_lines = count_lines_with(
            juju,
            unit,
            "/var/log/kafka/server.log",
            "DEBUG",
        )
        assert total_lines > 0

    # cleanup
    juju.config(APP_NAME, {"log-level": "INFO"})
    juju.wait(
        lambda status: all_active_idle(status, APP_NAME), delay=2, successes=15, timeout=1000
    )
