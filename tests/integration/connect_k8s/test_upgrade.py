#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
from time import sleep

import pytest
from jubilant_adapters import JujuFixture, gather

from integration.connect_k8s.helpers import (
    APP_NAME,
    DEFAULT_API_PORT,
    IMAGE_RESOURCE_KEY,
    IMAGE_URI,
    KAFKA_APP,
    KAFKA_CHANNEL,
    check_connect_endpoints_status,
)

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker

CHANNEL = "edge"


def test_in_place_upgrade(juju: JujuFixture, kafka_connect_charm):
    # deploy kafka & kafka-connect
    gather(
        juju.ext.model.deploy(
            APP_NAME,
            channel=CHANNEL,
            application_name=APP_NAME,
            num_units=3,
            trust=True,
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
    juju.ext.model.add_relation(APP_NAME, KAFKA_APP)

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, KAFKA_APP], idle_period=60, timeout=1200, status="active"
        )

    leader_unit = None
    for unit in juju.ext.model.applications[APP_NAME].units:
        if unit.is_leader_from_status():
            leader_unit = unit
    assert leader_unit

    logger.info("Calling pre-upgrade-check...")
    action = leader_unit.run_action("pre-upgrade-check")
    action.wait()
    juju.ext.model.wait_for_idle(apps=[APP_NAME], timeout=1000, idle_period=15, status="active")

    logger.info("Upgrading Connect...")
    juju.ext.model.applications[APP_NAME].refresh(
        path=kafka_connect_charm,
        resources={IMAGE_RESOURCE_KEY: IMAGE_URI},
    )

    with juju.ext.fast_forward(fast_interval="20s"):
        sleep(60)

    juju.ext.model.wait_for_idle(
        apps=[APP_NAME], timeout=1000, idle_period=90, raise_on_error=False
    )

    action = leader_unit.run_action("resume-upgrade")
    action.wait()
    juju.ext.model.wait_for_idle(apps=[APP_NAME], timeout=1000, idle_period=30, status="active")

    with juju.ext.fast_forward(fast_interval="20s"):
        sleep(60)

    check_connect_endpoints_status(juju, app_name=APP_NAME, port=DEFAULT_API_PORT)
