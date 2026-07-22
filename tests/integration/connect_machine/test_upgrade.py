#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time

import pytest
from jubilant_adapters import JujuFixture, gather

from integration.connect_machine.helpers import (
    APP_NAME,
    DEFAULT_API_PORT,
    KAFKA_APP,
    check_connect_endpoints_status,
    deploy_kafka,
)

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker

CHANNEL = "edge"


def test_in_place_upgrade(juju: JujuFixture, kafka_version: int, kafka_connect_charm):
    # deploy kafka & kafka-connect
    gather(
        juju.ext.model.deploy(
            APP_NAME,
            channel=CHANNEL,
            application_name=APP_NAME,
            num_units=1,
            series="noble",
        ),
        deploy_kafka(juju, kafka_version),
    )

    juju.ext.model.wait_for_idle(apps=[APP_NAME, KAFKA_APP], timeout=3000)

    assert juju.ext.model.applications[KAFKA_APP].status == "active"
    assert juju.ext.model.applications[APP_NAME].status == "blocked"

    juju.ext.model.add_relation(APP_NAME, KAFKA_APP)

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, KAFKA_APP], idle_period=60, timeout=1000, status="active"
        )

    logger.info("Calling pre-upgrade-check")
    action = juju.ext.model.applications[APP_NAME].units[0].run_action("pre-upgrade-check")
    action.wait()

    # ensure action completes
    time.sleep(10)

    logger.info("Upgrading Connect...")
    juju.ext.model.applications[APP_NAME].refresh(path=kafka_connect_charm)
    juju.ext.model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        timeout=1000,
        idle_period=120,
    )

    check_connect_endpoints_status(juju, app_name=APP_NAME, port=DEFAULT_API_PORT)
