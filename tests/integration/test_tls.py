#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import base64
import json
import logging
import os

import pytest
from charms.tls_certificates_interface.v1.tls_certificates import generate_private_key
from pytest_operator.plugin import OpsTest

from literals import (
    REL_NAME,
    SECURITY_PROTOCOL_PORTS,
    TLS_RELATION,
    TRUSTED_CERTIFICATE_RELATION,
    ZK,
)

from .helpers import (
    APP_NAME,
    REL_NAME_ADMIN,
    check_tls,
    create_test_topic,
    extract_ca,
    extract_private_key,
    get_active_brokers,
    get_address,
    get_kafka_zk_relation_data,
    search_secrets,
    set_mtls_client_acls,
    set_tls_private_key,
)
from .test_charm import DUMMY_NAME

logger = logging.getLogger(__name__)

TLS_NAME = "self-signed-certificates"
CERTS_NAME = "tls-certificates-operator"
MTLS_NAME = "mtls"
TLS_REQUIRER = "tls-certificates-requirer"


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_deploy_tls(ops_test: OpsTest, kafka_charm):
    tls_config = {"ca-common-name": "kafka"}

    await asyncio.gather(
        # FIXME (certs): Unpin the revision once the charm is fixed
        ops_test.model.deploy(
            TLS_NAME, channel="edge", config=tls_config, series="jammy", revision=163
        ),
        ops_test.model.deploy(ZK, channel="edge", series="jammy", application_name=ZK),
        ops_test.model.deploy(
            kafka_charm,
            application_name=APP_NAME,
            series="jammy",
            config={
                "ssl_principal_mapping_rules": "RULE:^.*[Cc][Nn]=([a-zA-Z0-9.]*).*$/$1/L,DEFAULT"
            },
        ),
    )
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[ZK].units) == 1)
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK, TLS_NAME], idle_period=15, timeout=1800)

    assert ops_test.model.applications[APP_NAME].status == "blocked"
    assert ops_test.model.applications[ZK].status == "active"
    assert ops_test.model.applications[TLS_NAME].status == "active"

    await ops_test.model.add_relation(TLS_NAME, ZK)

    # Relate Zookeeper to TLS
    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(apps=[TLS_NAME, ZK], idle_period=30, status="active")


@pytest.mark.abort_on_fail
async def test_kafka_tls(ops_test: OpsTest, app_charm):
    """Tests TLS on Kafka.

    Relates Zookeper[TLS] with Kafka[Non-TLS]. This leads to a blocked status.
    Afterwards, relate Kafka to TLS operator, which unblocks the application.
    """
    # Relate Zookeeper[TLS] to Kafka[Non-TLS]
    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.add_relation(ZK, APP_NAME)
        await ops_test.model.wait_for_idle(
            apps=[ZK], idle_period=15, timeout=1000, status="active"
        )

        # Unit is on 'blocked' but whole app is on 'waiting'
        assert ops_test.model.applications[APP_NAME].status == "blocked"

    # Set a custom private key, by running set-tls-private-key action with no parameters,
    # as this will generate a random one
    num_unit = 0
    await set_tls_private_key(ops_test)

    # Extract the key
    private_key = extract_private_key(
        ops_test=ops_test,
        unit_name=f"{APP_NAME}/{num_unit}",
    )

    # ensuring at least a few update-status
    await ops_test.model.add_relation(f"{APP_NAME}:{TLS_RELATION}", TLS_NAME)
    async with ops_test.fast_forward(fast_interval="20s"):
        await asyncio.sleep(60)

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, ZK, TLS_NAME], idle_period=30, timeout=1200, status="active"
    )

    kafka_address = await get_address(ops_test=ops_test, app_name=APP_NAME)

    assert not check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    )

    await asyncio.gather(
        ops_test.model.deploy(app_charm, application_name=DUMMY_NAME, num_units=1, series="jammy"),
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME], timeout=1000, idle_period=30)

    # ensuring at least a few update-status
    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    async with ops_test.fast_forward(fast_interval="20s"):
        await asyncio.sleep(60)

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, DUMMY_NAME], idle_period=30, status="active"
    )

    assert check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    )

    # Rotate credentials
    new_private_key = generate_private_key().decode("utf-8")

    await set_tls_private_key(ops_test, key=new_private_key)

    # ensuring key event actually runs
    async with ops_test.fast_forward(fast_interval="10s"):
        await asyncio.sleep(60)

    # Extract the key
    private_key_2 = extract_private_key(
        ops_test=ops_test,
        unit_name=f"{APP_NAME}/{num_unit}",
    )

    assert private_key != private_key_2
    assert private_key_2 == new_private_key


@pytest.mark.abort_on_fail
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
        CERTS_NAME, channel="stable", config=tls_config, series="jammy", application_name=MTLS_NAME
    )
    await ops_test.model.wait_for_idle(apps=[MTLS_NAME], timeout=1000, idle_period=15)
    await ops_test.model.add_relation(
        f"{APP_NAME}:{TRUSTED_CERTIFICATE_RELATION}", f"{MTLS_NAME}:{TLS_RELATION}"
    )
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, MTLS_NAME], idle_period=60, timeout=2000, status="active"
    )

    # getting kafka ca and address
    broker_ca = extract_ca(ops_test=ops_test, unit_name=f"{APP_NAME}/0")

    address = await get_address(ops_test, app_name=APP_NAME)
    ssl_port = SECURITY_PROTOCOL_PORTS["SSL", "SSL"].client
    sasl_port = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    ssl_bootstrap_server = f"{address}:{ssl_port}"
    sasl_bootstrap_server = f"{address}:{sasl_port}"

    # setting ACLs using normal sasl port
    await set_mtls_client_acls(ops_test, bootstrap_server=sasl_bootstrap_server)

    num_messages = 10

    # running mtls producer
    action = await ops_test.model.units.get(f"{DUMMY_NAME}/0").run_action(
        "run-mtls-producer",
        **{
            "bootstrap-server": ssl_bootstrap_server,
            "broker-ca": base64.b64encode(broker_ca.encode("utf-8")).decode("utf-8"),
            "num-messages": num_messages,
        },
    )

    response = await action.wait()

    assert response.results.get("success", None) == "TRUE"

    offsets_action = await ops_test.model.units.get(f"{DUMMY_NAME}/0").run_action(
        "get-offsets",
        **{
            "bootstrap-server": ssl_bootstrap_server,
        },
    )

    response = await offsets_action.wait()

    topic_name, min_offset, max_offset = response.results["output"].strip().split(":")

    assert topic_name == "TEST-TOPIC"
    assert min_offset == "0"
    assert max_offset == str(num_messages)


@pytest.mark.abort_on_fail
async def test_truststore_live_reload(ops_test: OpsTest):
    """Tests truststore live reload functionality using kafka-python client."""
    requirer = "other-req/0"
    test_msg = {"test": 123456}

    await ops_test.model.deploy(
        TLS_NAME, channel="stable", series="jammy", application_name="other-ca"
    )
    await ops_test.model.deploy(
        TLS_REQUIRER, channel="stable", series="jammy", application_name="other-req"
    )

    await ops_test.model.add_relation("other-ca", "other-req")

    await ops_test.model.wait_for_idle(
        apps=["other-ca", "other-req"], idle_period=60, timeout=2000, status="active"
    )

    # retrieve required certificates and private key from secrets
    local_store = {
        "private_key": search_secrets(ops_test=ops_test, owner=requirer, search_key="private-key"),
        "cert": search_secrets(ops_test=ops_test, owner=requirer, search_key="certificate"),
        "ca_cert": search_secrets(ops_test=ops_test, owner=requirer, search_key="ca-certificate"),
        "broker_ca": extract_ca(ops_test=ops_test, unit_name=f"{APP_NAME}/0"),
    }

    certs_operator_config = {
        "generate-self-signed-certificates": "false",
        "certificate": base64.b64encode(local_store["cert"].encode("utf-8")).decode("utf-8"),
        "ca-certificate": base64.b64encode(local_store["ca_cert"].encode("utf-8")).decode("utf-8"),
    }

    await ops_test.model.deploy(
        CERTS_NAME,
        channel="stable",
        series="jammy",
        application_name="other-op",
        config=certs_operator_config,
    )

    await ops_test.model.wait_for_idle(
        apps=["other-op"], idle_period=60, timeout=2000, status="active"
    )

    # We don't expect a broker restart here because of truststore live reload
    await ops_test.model.add_relation(f"{APP_NAME}:{TRUSTED_CERTIFICATE_RELATION}", "other-op")

    await ops_test.model.wait_for_idle(
        apps=["other-op", APP_NAME], idle_period=60, timeout=2000, status="active"
    )

    for key_, content in local_store.items():
        with open(f"test_{key_}", "w", encoding="utf-8") as f:
            f.write(content)

    address = await get_address(ops_test, app_name=APP_NAME)
    ssl_port = SECURITY_PROTOCOL_PORTS["SSL", "SSL"].client
    ssl_bootstrap_server = f"{address}:{ssl_port}"
    sasl_port = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    sasl_bootstrap_server = f"{address}:{sasl_port}"

    # create `test` topic and set ACLs
    await create_test_topic(ops_test, bootstrap_server=sasl_bootstrap_server)

    # quickly test the producer and consumer side authentication & authorization
    client_config = {
        "bootstrap_servers": ssl_bootstrap_server,
        "security_protocol": "SSL",
        "api_version": (0, 10),
        "ssl_cafile": "test_broker_ca",
        "ssl_certfile": "test_cert",
        "ssl_keyfile": "test_private_key",
        "ssl_check_hostname": False,
    }

    import kafka

    producer = kafka.KafkaProducer(
        **client_config,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )

    producer.send("test", test_msg)

    consumer = kafka.KafkaConsumer("test", **client_config, auto_offset_reset="earliest")

    msg = next(consumer)

    assert json.loads(msg.value) == test_msg

    # cleanup
    await ops_test.model.remove_application("other-ca", block_until_done=True)
    await ops_test.model.remove_application("other-op", block_until_done=True)
    await ops_test.model.remove_application("other-req", block_until_done=True)
    for key_ in local_store:
        os.remove(f"test_{key_}")


@pytest.mark.abort_on_fail
async def test_mtls_broken(ops_test: OpsTest):
    await ops_test.model.remove_application(MTLS_NAME, block_until_done=True)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        idle_period=30,
        timeout=2000,
    )


@pytest.mark.abort_on_fail
async def test_kafka_tls_scaling(ops_test: OpsTest):
    """Scale the application while using TLS to check that new units will configure correctly."""
    await ops_test.model.applications[APP_NAME].add_units(count=2)
    await ops_test.model.block_until(
        lambda: len(ops_test.model.applications[APP_NAME].units) == 3, timeout=1000
    )

    # Wait for model to settle
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", idle_period=40, timeout=1000, raise_on_error=False
    )

    kafka_zk_relation_data = get_kafka_zk_relation_data(
        unit_name=f"{APP_NAME}/2",
        ops_test=ops_test,
        owner=ZK,
    )
    active_brokers = get_active_brokers(config=kafka_zk_relation_data)
    chroot = kafka_zk_relation_data.get("database", kafka_zk_relation_data.get("chroot", ""))
    assert f"{chroot}/brokers/ids/0" in active_brokers
    assert f"{chroot}/brokers/ids/1" in active_brokers
    assert f"{chroot}/brokers/ids/2" in active_brokers

    kafka_address = await get_address(ops_test=ops_test, app_name=APP_NAME, unit_num=2)
    assert check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    )

    # remove relation and check connection again
    await ops_test.model.applications[APP_NAME].remove_relation(
        f"{APP_NAME}:{REL_NAME}", f"{DUMMY_NAME}:{REL_NAME_ADMIN}"
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME])
    assert not check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    )


async def test_tls_removed(ops_test: OpsTest):
    await ops_test.model.remove_application(TLS_NAME, block_until_done=True)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, ZK], timeout=3600, idle_period=30, status="active"
    )

    kafka_address = await get_address(ops_test=ops_test, app_name=APP_NAME)
    assert not check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    )
