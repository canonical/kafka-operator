#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import time

import pytest
from pytest_operator.plugin import OpsTest

from literals import CHARM_KEY, ZK
from utils import get_active_brokers

from .helpers import get_kafka_zk_relation_data

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
async def test_kafka_simple_scale_up(ops_test: OpsTest, kafka_charm):
    await asyncio.gather(
        ops_test.model.deploy(
            "zookeeper", channel="edge", application_name=ZK, num_units=1, series="jammy"
        ),
        ops_test.model.deploy(
            kafka_charm, application_name=CHARM_KEY, num_units=1, series="jammy"
        ),
    )
    await ops_test.model.wait_for_idle(apps=[CHARM_KEY, ZK], idle_period=30, timeout=1800)
    await ops_test.model.add_relation(CHARM_KEY, ZK)
    await ops_test.model.wait_for_idle(
        apps=[CHARM_KEY, ZK], idle_period=30, timeout=1200, status="active"
    )

    await ops_test.model.applications[CHARM_KEY].add_units(count=2)
    await ops_test.model.wait_for_idle(
        apps=[CHARM_KEY], status="active", timeout=600, idle_period=30, wait_for_exact_units=3
    )

    kafka_zk_relation_data = get_kafka_zk_relation_data(
        unit_name="kafka/2", model_full_name=ops_test.model_full_name
    )
    active_brokers = get_active_brokers(zookeeper_config=kafka_zk_relation_data)
    chroot = kafka_zk_relation_data.get("chroot", "")
    assert f"{chroot}/brokers/ids/0" in active_brokers
    assert f"{chroot}/brokers/ids/1" in active_brokers
    assert f"{chroot}/brokers/ids/2" in active_brokers


@pytest.mark.abort_on_fail
async def test_kafka_simple_scale_down(ops_test: OpsTest):
    await ops_test.model.applications[CHARM_KEY].destroy_units(f"{CHARM_KEY}/1")
    await ops_test.model.wait_for_idle(
        apps=[CHARM_KEY], status="active", timeout=1000, idle_period=30, wait_for_exact_units=2
    )

    time.sleep(30)

    kafka_zk_relation_data = get_kafka_zk_relation_data(
        unit_name="kafka/2", model_full_name=ops_test.model_full_name
    )
    active_brokers = get_active_brokers(zookeeper_config=kafka_zk_relation_data)
    chroot = kafka_zk_relation_data.get("chroot", "")
    assert f"{chroot}/brokers/ids/0" in active_brokers
    assert f"{chroot}/brokers/ids/1" not in active_brokers
    assert f"{chroot}/brokers/ids/2" in active_brokers
