#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import base64
import logging

import pytest
from charms.tls_certificates_interface.v1.tls_certificates import generate_private_key
from pytest_operator.plugin import OpsTest

from literals import (
    CHARM_KEY,
    REL_NAME,
    SECURITY_PROTOCOL_PORTS,
    TLS_RELATION,
    TRUSTED_CERTIFICATE_RELATION,
    ZK,
)
from utils import get_active_brokers

from .helpers import (
    REL_NAME_ADMIN,
    check_tls,
    extract_ca,
    extract_private_key,
    get_address,
    get_kafka_zk_relation_data,
    set_mtls_client_acls,
    set_tls_private_key,
    show_unit,
)
from .test_charm import DUMMY_NAME

logger = logging.getLogger(__name__)

TLS_NAME = "tls-certificates-operator"
MTLS_NAME = "mtls"


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_deploy_tls(ops_test: OpsTest, kafka_charm):
    tls_config = {"generate-self-signed-certificates": "true", "ca-common-name": "kafka"}

    await asyncio.gather(
        ops_test.model.deploy(TLS_NAME, channel="beta", config=tls_config, series="jammy"),
        ops_test.model.deploy(ZK, channel="edge", series="jammy", application_name=ZK),
        ops_test.model.deploy(kafka_charm, application_name=CHARM_KEY, series="jammy"),
    )
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[ZK].units) == 1)
    await ops_test.model.wait_for_idle(
        apps=[CHARM_KEY, ZK, TLS_NAME], idle_period=15, timeout=1800
    )

    assert ops_test.model.applications[CHARM_KEY].status == "blocked"
    assert ops_test.model.applications[ZK].status == "active"
    assert ops_test.model.applications[TLS_NAME].status == "active"

    # Relate Zookeeper to TLS
    async with ops_test.fast_forward():
        await ops_test.model.add_relation(TLS_NAME, ZK)
        await ops_test.model.wait_for_idle(apps=[TLS_NAME, ZK], idle_period=15)

        assert ops_test.model.applications[TLS_NAME].status == "active"
        assert ops_test.model.applications[ZK].status == "active"


@pytest.mark.abort_on_fail
async def test_kafka_tls(ops_test: OpsTest, app_charm):
    """Tests TLS on Kafka.

    Relates Zookeper[TLS] with Kakfa[Non-TLS]. This leads to a blocked status.
    Afterwards, relate Kafka to TLS operator, which unblocks the application.
    """
    # Relate Zookeeper[TLS] to Kafka[Non-TLS]
    async with ops_test.fast_forward():
        await ops_test.model.add_relation(ZK, CHARM_KEY)
        await ops_test.model.wait_for_idle(apps=[ZK], idle_period=15, timeout=1000, status="active")
        assert ops_test.model.applications[CHARM_KEY].status == "blocked"

    # Set a custom private key, by running set-tls-private-key action with no parameters,
    # as this will generate a random one
    num_unit = 0
    await set_tls_private_key(ops_test)

    # Extract the key
    private_key = extract_private_key(
        show_unit(f"{CHARM_KEY}/{num_unit}", model_full_name=ops_test.model_full_name), unit=0
    )

    async with ops_test.fast_forward():
        await ops_test.model.add_relation(f"{CHARM_KEY}:{TLS_RELATION}", TLS_NAME)
        logger.info("Relate Kafka to TLS")
        await ops_test.model.wait_for_idle(
            apps=[CHARM_KEY, ZK, TLS_NAME], idle_period=30, timeout=1200, status="active"
        )

    assert ops_test.model.applications[CHARM_KEY].status == "active"
    assert ops_test.model.applications[ZK].status == "active"

    kafka_address = await get_address(ops_test=ops_test, app_name=CHARM_KEY)
    assert not check_tls(ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL"].client)

    async with ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.deploy(
                app_charm, application_name=DUMMY_NAME, num_units=1, series="jammy"
            ),
        )
        await ops_test.model.wait_for_idle(
            apps=[CHARM_KEY, DUMMY_NAME], timeout=1000, idle_period=15
        )
        await ops_test.model.add_relation(CHARM_KEY, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
        await ops_test.model.wait_for_idle(
            apps=[CHARM_KEY, DUMMY_NAME], timeout=1000, idle_period=15
        )

        assert ops_test.model.applications[CHARM_KEY].status == "active"
        assert ops_test.model.applications[DUMMY_NAME].status == "active"

    assert check_tls(ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL"].client)

    # Rotate credentials
    new_private_key = generate_private_key().decode("utf-8")

    await set_tls_private_key(ops_test, key=new_private_key)

    # Extract the key
    private_key_2 = extract_private_key(
        show_unit(f"{CHARM_KEY}/{num_unit}", model_full_name=ops_test.model_full_name), unit=0
    )

    assert private_key != private_key_2
    assert private_key_2 == new_private_key


async def test_mtls(ops_test: OpsTest):
    # creating the signed external cert on the unit
    action = await ops_test.model.units.get(f"{DUMMY_NAME}/0").run_action("create-certificate")
    response = await action.wait()
    client_certificate = response.results["client-certificate"]
    client_ca = response.results["client-ca"]

    encoded_client_certificate = base64.b64encode(client_certificate.encode("utf-8")).decode(
        "utf-8"
    )
    encoded_client_ca = base64.b64encode(client_ca.encode("utf-8")).decode("utf-8")


    # deploying mtls operator with certs
    tls_config = {
        "generate-self-signed-certificates": "false",
        "certificate": encoded_client_certificate,
        "ca-certificate": encoded_client_ca,
    }
    await ops_test.model.deploy(
        TLS_NAME, channel="beta", config=tls_config, series="jammy", application_name=MTLS_NAME
    )
    await ops_test.model.wait_for_idle(apps=[MTLS_NAME], timeout=1000, idle_period=15)
    async with ops_test.fast_forward():
        await ops_test.model.add_relation(
            f"{CHARM_KEY}:{TRUSTED_CERTIFICATE_RELATION}", f"{MTLS_NAME}:{TLS_RELATION}"
        )
        await ops_test.model.wait_for_idle(
            apps=[CHARM_KEY, MTLS_NAME], idle_period=15, timeout=1000
        )

    # getting kafka ca and address
    broker_ca = extract_ca(show_unit(f"{CHARM_KEY}/0", model_full_name=ops_test.model_full_name))
    address = await get_address(ops_test, app_name=CHARM_KEY)
    ssl_port = SECURITY_PROTOCOL_PORTS["SSL"].client
    sasl_port = SECURITY_PROTOCOL_PORTS["SASL_SSL"].client
    ssl_bootstrap_server = f"{address}:{ssl_port}"
    sasl_bootstrap_server = f"{address}:{sasl_port}"

    # setting ACLs using normal sasl port
    await set_mtls_client_acls(ops_test, bootstrap_server=sasl_bootstrap_server)

    # running mtls producer
    action = await ops_test.model.units.get(f"{DUMMY_NAME}/0").run_action(
        "run-mtls-producer", **{"bootstrap-server": ssl_bootstrap_server, "broker-ca": broker_ca}
    )

    response = await action.wait()

    assert response.results.get("success", None) == "TRUE"


async def test_kafka_tls_scaling(ops_test: OpsTest):
    """Scale the application while using TLS to check that new units will configure correctly."""
    await ops_test.model.applications[CHARM_KEY].add_units(count=2)
    await ops_test.model.block_until(
        lambda: len(ops_test.model.applications[CHARM_KEY].units) == 3, timeout=1000
    )
    # Wait for model to settle
    await ops_test.model.wait_for_idle(
        apps=[CHARM_KEY],
        status="active",
        idle_period=40,
        timeout=1000,
    )

    kafka_zk_relation_data = get_kafka_zk_relation_data(
        unit_name=f"{CHARM_KEY}/2", model_full_name=ops_test.model_full_name
    )
    active_brokers = get_active_brokers(zookeeper_config=kafka_zk_relation_data)
    chroot = kafka_zk_relation_data.get("chroot", "")
    assert f"{chroot}/brokers/ids/0" in active_brokers
    assert f"{chroot}/brokers/ids/1" in active_brokers
    assert f"{chroot}/brokers/ids/2" in active_brokers

    kafka_address = await get_address(ops_test=ops_test, app_name=CHARM_KEY, unit_num=2)
    assert check_tls(ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL"].client)

    # remove relation and check connection again
    await ops_test.model.applications[CHARM_KEY].remove_relation(
        f"{CHARM_KEY}:{REL_NAME}", f"{DUMMY_NAME}:{REL_NAME_ADMIN}"
    )
    await ops_test.model.wait_for_idle(apps=[CHARM_KEY])
    assert not check_tls(ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL"].client)
