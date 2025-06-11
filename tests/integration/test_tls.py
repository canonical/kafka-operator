#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import json
import logging
import os
import tempfile

import kafka
import pytest
from charms.tls_certificates_interface.v3.tls_certificates import generate_private_key
from pytest_operator.plugin import OpsTest

from literals import (
    CERTIFICATE_TRANSFER_RELATION,
    REL_NAME,
    SECURITY_PROTOCOL_PORTS,
    TLS_RELATION,
    ZK,
)

from .helpers import (
    APP_NAME,
    REL_NAME_PRODUCER,
    check_tls,
    create_test_topic,
    extract_private_key,
    get_active_brokers,
    get_address,
    get_kafka_zk_relation_data,
    get_provider_data,
    list_truststore_aliases,
    search_secrets,
    set_tls_private_key,
    sign_manual_certs,
)
from .test_charm import DUMMY_NAME

logger = logging.getLogger(__name__)

TLS_NAME = "self-signed-certificates"
CERTS_NAME = "tls-certificates-operator"
TLS_REQUIRER = "tls-certificates-requirer"
MANUAL_TLS_NAME = "manual-tls-certificates"


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
                # "ssl_principal_mapping_rules": "RULE:^.*[Cc][Nn]=([a-zA-Z0-9.]*).*$/$1/L,DEFAULT"
            },
        ),
    )
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[ZK].units) == 1)
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK, TLS_NAME], idle_period=15, timeout=1800)

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
    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_PRODUCER}")
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

    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, DUMMY_NAME], idle_period=30, status="active"
        )

    # run mtls producer
    num_messages = 10
    action = await ops_test.model.units.get(f"{DUMMY_NAME}/0").run_action(
        "run-mtls-producer",
        **{"num-messages": num_messages},
    )

    response = await action.wait()
    assert response.results.get("success", None) == "TRUE"

    provider_data = get_provider_data(
        ops_test,
        owner=DUMMY_NAME,
        unit_name=f"{DUMMY_NAME}/0",
        relation_interface=REL_NAME_PRODUCER,
    )

    offsets_action = await ops_test.model.units.get(f"{DUMMY_NAME}/0").run_action(
        "get-offsets",
        **{
            "bootstrap-server": provider_data["endpoints"],
        },
    )

    response = await offsets_action.wait()

    topic_name, min_offset, max_offset = response.results["output"].strip().split(":")

    assert topic_name == "test-topic"
    assert min_offset == "0"
    assert max_offset == str(num_messages)


@pytest.mark.abort_on_fail
async def test_certificate_transfer(ops_test: OpsTest):
    """Tests truststore live reload functionality using kafka-python client."""
    requirer = "other-req/0"
    test_msg = {"test": 123456}

    await ops_test.model.deploy(
        TLS_NAME,
        application_name="other-ca",
        channel="1/stable",
    )
    await ops_test.model.deploy(
        TLS_REQUIRER, channel="stable", application_name="other-req", revision=102
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
        "broker_ca": search_secrets(
            ops_test=ops_test, owner=f"{APP_NAME}/0", search_key="ca-cert"
        ),
    }

    # Transfer other-ca's CA certificate via the client-cas relation
    # We don't expect a broker restart here because of truststore live reload
    await ops_test.model.add_relation(
        f"{APP_NAME}:{CERTIFICATE_TRANSFER_RELATION}", "other-ca:send-ca-cert"
    )

    await ops_test.model.wait_for_idle(
        apps=["other-ca", APP_NAME], idle_period=60, timeout=2000, status="active"
    )

    address = await get_address(ops_test, app_name=APP_NAME, unit_num=0)
    ssl_port = SECURITY_PROTOCOL_PORTS["SSL", "SSL"].client
    ssl_bootstrap_server = f"{address}:{ssl_port}"
    sasl_port = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    sasl_bootstrap_server = f"{address}:{sasl_port}"

    # create `test` topic and set ACLs
    await create_test_topic(ops_test, bootstrap_server=sasl_bootstrap_server)

    # quickly test the producer and consumer side authentication & authorization
    tmp_dir = tempfile.TemporaryDirectory()
    tmp_paths = {}
    for key, content in local_store.items():
        tmp_paths[key] = os.path.join(tmp_dir.name, key)
        with open(tmp_paths[key], "w", encoding="utf-8") as f:
            f.write(content)

    client_config = {
        "bootstrap_servers": ssl_bootstrap_server,
        "security_protocol": "SSL",
        "api_version": (0, 10),
        "ssl_cafile": tmp_paths["broker_ca"],
        "ssl_certfile": tmp_paths["cert"],
        "ssl_keyfile": tmp_paths["private_key"],
        "ssl_check_hostname": False,
    }

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
    await ops_test.model.remove_application("other-req", block_until_done=True)
    tmp_dir.cleanup()


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


@pytest.mark.abort_on_fail
async def test_mtls_broken(ops_test: OpsTest):
    # remove client relation and check connection
    await ops_test.model.applications[APP_NAME].remove_relation(
        f"{APP_NAME}:{REL_NAME}", f"{DUMMY_NAME}:{REL_NAME_PRODUCER}"
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME])

    for unit_num in range(len(ops_test.model.applications[APP_NAME].units)):
        kafka_address = await get_address(ops_test=ops_test, app_name=APP_NAME, unit_num=unit_num)
        assert not check_tls(
            ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
        )
        assert not check_tls(ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SSL", "SSL"].client)


@pytest.mark.abort_on_fail
async def test_tls_removed(ops_test: OpsTest):
    await ops_test.model.remove_application(TLS_NAME, block_until_done=True)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, ZK], timeout=3600, idle_period=30, status="active", raise_on_error=False
    )

    kafka_address = await get_address(ops_test=ops_test, app_name=APP_NAME)
    assert not check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    )

    # check proper cleanup of TLS-related files.
    for unit in ops_test.model.applications[APP_NAME].units:
        ret, stdout, _ = await ops_test.juju(
            "ssh", unit.name, "sudo ls /var/snap/charmed-kafka/current/etc/kafka"
        )
        assert not ret
        file_extensions = {f.split(".")[-1] for f in stdout.split() if f}
        logging.info(f"{', '.join(file_extensions)} files found on {unit.name}")
        assert not {"pem", "key", "p12", "jks"} & file_extensions


@pytest.mark.abort_on_fail
async def test_manual_tls_chain(ops_test: OpsTest):
    await ops_test.model.deploy(MANUAL_TLS_NAME)

    await asyncio.gather(
        ops_test.model.add_relation(f"{APP_NAME}:{TLS_RELATION}", MANUAL_TLS_NAME),
        ops_test.model.add_relation(ZK, MANUAL_TLS_NAME),
    )

    # ensuring enough time for multiple rolling-restart with update-status
    async with ops_test.fast_forward(fast_interval="30s"):
        await asyncio.sleep(180)

    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, ZK, MANUAL_TLS_NAME],
            idle_period=30,
            timeout=1000,
            raise_on_error=False,
        )

    sign_manual_certs(ops_test)

    # verifying brokers + servers can communicate with one-another
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, ZK, MANUAL_TLS_NAME],
        idle_period=30,
        timeout=1000,
        raise_on_error=False,
        status="active",
    )

    # verifying the chain is in there
    trusted_aliases = await list_truststore_aliases(ops_test)

    assert len(trusted_aliases) == 3  # cert, intermediate, rootca

    # verifying TLS is enabled and working
    kafka_address = await get_address(ops_test=ops_test, app_name=APP_NAME)
    assert check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].internal
    )
