#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.
import logging

from jubilant_adapters import JujuFixture, gather

from integration.connect_k8s.helpers import (
    APP_NAME,
    DEFAULT_API_PORT,
    IMAGE_RESOURCE_KEY,
    IMAGE_URI,
    KAFKA_APP,
    KAFKA_CHANNEL,
    check_connect_endpoints_status,
    make_connect_api_request,
)

logger = logging.getLogger(__name__)


def test_deploy_charms(juju: JujuFixture, kafka_connect_charm):
    """Deploys kafka-connect charm along kafka (in KRaft mode)."""
    # deploy kafka & kafka-connect
    gather(
        juju.ext.model.deploy(
            kafka_connect_charm,
            application_name=APP_NAME,
            num_units=1,
            resources={IMAGE_RESOURCE_KEY: IMAGE_URI},
        ),
        juju.ext.model.deploy(
            KAFKA_APP,
            channel=KAFKA_CHANNEL,
            application_name=KAFKA_APP,
            num_units=1,
            config={"roles": "broker,controller"},
        ),
    )

    juju.ext.model.wait_for_idle(apps=[APP_NAME, KAFKA_APP], timeout=3000)

    assert juju.ext.model.applications[APP_NAME].status == "blocked"

    juju.ext.model.add_relation(APP_NAME, KAFKA_APP)

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, KAFKA_APP], idle_period=60, timeout=1000, status="active"
        )


def test_api_endpoint(juju: JujuFixture):
    """Checks API endpoint connectivity using a socket."""
    status = check_connect_endpoints_status(juju, app_name=APP_NAME, port=DEFAULT_API_PORT)

    # assert all endpoints are up
    assert all(status.values())


def test_scale_out(juju: JujuFixture):
    """Checks connect workers scaling functionality."""
    juju.ext.model.applications[APP_NAME].add_units(count=2)
    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME], idle_period=30, timeout=1200, status="active", wait_for_exact_units=3
        )

    check_connect_endpoints_status(juju, app_name=APP_NAME, port=DEFAULT_API_PORT)


def test_auth(juju: JujuFixture):
    """Checks authentication is enabled on all API endpoints."""
    for unit in juju.ext.model.applications[APP_NAME].units:
        response = make_connect_api_request(juju, unit=unit, auth_enabled=False)
        assert response.status_code == 401

        response = make_connect_api_request(juju, unit=unit, auth_enabled=True)
        assert response.status_code == 200


def test_broken_kafka_relation(juju: JujuFixture):

    juju.juju("remove-relation", APP_NAME, KAFKA_APP)
    juju.ext.model.wait_for_idle(apps=[APP_NAME, KAFKA_APP], timeout=1000, idle_period=30)

    status = check_connect_endpoints_status(juju, app_name=APP_NAME, port=DEFAULT_API_PORT)

    assert juju.ext.model.applications[APP_NAME].status == "blocked"
    # assert all endpoints are down
    assert not any(status.values())
