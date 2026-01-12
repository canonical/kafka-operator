#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time

import jubilant
import pytest

from integration.helpers import (
    APP_NAME,
    DUMMY_NAME,
    REL_NAME_ADMIN,
)
from integration.helpers.jubilant import (
    BASE,
    all_active_idle,
    check_logs,
    deploy_cluster,
    produce_and_check_logs,
)

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker


def test_in_place_upgrade(juju: jubilant.Juju, kafka_charm, app_charm, kraft_mode, controller_app):
    deploy_cluster(juju=juju, charm=kafka_charm, kraft_mode=kraft_mode, num_broker=3)
    juju.deploy(app_charm, app=DUMMY_NAME, num_units=1, base=BASE)

    # Get kafka apps list for waiting
    kafka_apps = [APP_NAME] if kraft_mode == "single" else [APP_NAME, controller_app]

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=1800,
    )

    status = juju.status()
    assert status.apps[APP_NAME].app_status.current == "active"
    assert status.apps[controller_app].app_status.current == "active"

    juju.integrate(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=1800,
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

    # Find leader unit
    status = juju.status()
    leader_unit = None
    for unit_name, unit in status.apps[APP_NAME].units.items():
        if unit.leader:
            leader_unit = unit_name
            break
    assert leader_unit

    logger.info("Calling pre-refresh-check")
    juju.run(leader_unit, "pre-refresh-check")

    # ensure action completes
    time.sleep(10)

    logger.info("Upgrading Kafka...")
    juju.refresh(APP_NAME, path=str(kafka_charm))
    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=3,
        successes=40,
        timeout=1800,
    )

    logger.info("Check that produced messages can be consumed afterwards")
    check_logs(
        juju=juju,
        kafka_unit_name=f"{APP_NAME}/0",
        topic="hot-topic",
    )


def test_controller_upgrade_multinode(
    juju: jubilant.Juju, kafka_charm, kraft_mode, controller_app
):
    """Test upgrading the controller separately in multi-node mode."""
    if kraft_mode != "multi":
        logger.info(f"Skipping controller upgrade test because we're using {kraft_mode} mode.")
        return

    logger.info("Producing messages before controller upgrade")
    produce_and_check_logs(
        juju=juju,
        kafka_unit_name=f"{APP_NAME}/0",
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="controller-upgrade-topic",
        replication_factor=3,
        num_partitions=1,
    )

    # Find controller leader unit
    status = juju.status()
    controller_leader_unit = None
    for unit_name, unit in status.apps[controller_app].units.items():
        if unit.leader:
            controller_leader_unit = unit_name
            break
    assert controller_leader_unit

    logger.info("Calling pre-refresh-check on controller")
    juju.run(controller_leader_unit, "pre-refresh-check")

    # ensure action completes
    time.sleep(10)

    logger.info("Upgrading Controller...")
    juju.refresh(controller_app, path=str(kafka_charm))
    juju.wait(
        lambda status: all_active_idle(status, controller_app, APP_NAME),
        delay=3,
        successes=40,
        timeout=1800,
    )

    logger.info("Check that produced messages can still be consumed after controller upgrade")
    check_logs(
        juju=juju,
        kafka_unit_name=f"{APP_NAME}/0",
        topic="controller-upgrade-topic",
    )
