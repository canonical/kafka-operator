#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from helpers import (
    APP_NAME,
    ZK_NAME,
    check_tls,
    get_address,
    get_kafka_zk_relation_data,
)
from pytest_operator.plugin import OpsTest

from utils import get_active_brokers

logger = logging.getLogger(__name__)

TLS_NAME = "tls-certificates-operator"


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_deploy_tls(ops_test: OpsTest):
    kafka_charm = await ops_test.build_charm(".")
    tls_config = {"generate-self-signed-certificates": "true", "ca-common-name": "kafka"}

    await asyncio.gather(
        ops_test.model.deploy(TLS_NAME, channel="beta", config=tls_config, series="focal"),
        ops_test.model.deploy(ZK_NAME, channel="edge", num_units=3, series="focal"),
        ops_test.model.deploy(kafka_charm, application_name=APP_NAME, series="jammy"),
    )
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[ZK_NAME].units) == 3)
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME, TLS_NAME], timeout=1000)

    assert ops_test.model.applications[APP_NAME].status == "waiting"
    assert ops_test.model.applications[ZK_NAME].status == "active"
    assert ops_test.model.applications[TLS_NAME].status == "active"

    # Relate Zookeeper to TLS
    await ops_test.model.add_relation(TLS_NAME, ZK_NAME)
    logger.info("Relate Zookeeper to TLS")
    await ops_test.model.wait_for_idle(apps=[TLS_NAME, ZK_NAME], idle_period=40)

    assert ops_test.model.applications[TLS_NAME].status == "active"
    assert ops_test.model.applications[ZK_NAME].status == "active"


@pytest.mark.abort_on_fail
async def test_kafka_tls(ops_test: OpsTest):
    """Tests TLS on Kafka.

    Relates Zookeper[TLS] with Kakfa[Non-TLS]. This leads to a blocked status.
    Afterwards, relate Kafka to TLS operator, which unblocks the application.
    """
    # Relate Zookeeper[TLS] to Kafka[Non-TLS]
    await ops_test.model.add_relation(ZK_NAME, APP_NAME)
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME], idle_period=60, timeout=1000)

    assert ops_test.model.applications[APP_NAME].status == "blocked"

    await ops_test.model.add_relation(APP_NAME, TLS_NAME)
    logger.info("Relate Kafka to TLS")
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME, TLS_NAME], idle_period=60, timeout=1000
    )

    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[ZK_NAME].status == "active"

    kafka_address = await get_address(ops_test=ops_test, app_name=APP_NAME)
    logger.info("Check for Kafka TLS")
    check_tls(ip=kafka_address, port=9093)


async def test_kafka_tls_scaling(ops_test: OpsTest):
    """Scale the application while using TLS to check that new units will configure correctly."""
    await ops_test.model.applications[APP_NAME].add_units(count=2)
    logger.info("Scaling Kafka to 3 units")
    await ops_test.model.block_until(
        lambda: len(ops_test.model.applications[APP_NAME].units) == 3, timeout=1000
    )
    # Wait for model to settle
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        idle_period=40,
        timeout=1000,
    )

    kafka_zk_relation_data = get_kafka_zk_relation_data(
        unit_name="kafka/2", model_full_name=ops_test.model_full_name
    )
    active_brokers = get_active_brokers(zookeeper_config=kafka_zk_relation_data)
    chroot = kafka_zk_relation_data.get("chroot", "")
    assert f"{chroot}/brokers/ids/0" in active_brokers
    assert f"{chroot}/brokers/ids/1" in active_brokers
    assert f"{chroot}/brokers/ids/2" in active_brokers

    kafka_address = await get_address(ops_test=ops_test, app_name=APP_NAME, unit_num=2)
    check_tls(ip=kafka_address, port=9093)
