#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time

import pytest

from .adapters import JujuFixture, gather
from .helpers import (
    APP_NAME,
    DUMMY_NAME,
    REL_NAME_ADMIN,
    ZK_NAME,
    consume_and_check,
    produce_and_check_logs,
)

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker

CHANNEL = "3/stable"


def test_in_place_upgrade(juju: JujuFixture, kafka_charm, app_charm):
    gather(
        juju.ext.model.deploy(
            ZK_NAME,
            channel=CHANNEL,
            application_name=ZK_NAME,
            num_units=1,
        ),
        juju.ext.model.deploy(
            APP_NAME,
            application_name=APP_NAME,
            num_units=1,
            channel=CHANNEL,
        ),
        juju.ext.model.deploy(app_charm, application_name=DUMMY_NAME, num_units=1, series="jammy"),
    )

    juju.ext.model.add_relation(APP_NAME, ZK_NAME)

    juju.ext.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME, DUMMY_NAME], idle_period=30, timeout=1800, status="active"
    )

    assert juju.ext.model.applications[APP_NAME].status == "active"
    assert juju.ext.model.applications[ZK_NAME].status == "active"

    juju.ext.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    juju.ext.model.wait_for_idle(apps=[APP_NAME, ZK_NAME, DUMMY_NAME])

    juju.ext.model.applications[APP_NAME].add_units(count=2)
    juju.ext.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=600, idle_period=30, wait_for_exact_units=3
    )

    logger.info("Producing messages before upgrading")
    produce_and_check_logs(
        juju=juju,
        kafka_unit_name=f"{APP_NAME}/0",
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="hot-topic",
        replication_factor=3,
        num_partitions=1,
    )

    leader_unit = None
    for unit in juju.ext.model.applications[APP_NAME].units:
        if unit.is_leader_from_status():
            leader_unit = unit
    assert leader_unit

    logger.info("Calling pre-upgrade-check")
    action = leader_unit.run_action("pre-upgrade-check")
    action.wait()

    # ensure action completes
    time.sleep(10)

    logger.info("Upgrading Kafka...")
    juju.ext.model.applications[APP_NAME].refresh(path=kafka_charm)
    juju.ext.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=1000, idle_period=120)

    logger.info("Check that produced messages can be consumed afterwards")
    consume_and_check(
        juju=juju,
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="hot-topic",
    )
