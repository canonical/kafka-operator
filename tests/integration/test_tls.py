#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import base64
import json
import logging
import os
import tempfile

import kafka
import pytest
from charms.tls_certificates_interface.v3.tls_certificates import generate_private_key
from pytest_operator.plugin import OpsTest

from literals import SECURITY_PROTOCOL_PORTS, TLS_RELATION, TRUSTED_CERTIFICATE_RELATION

from .helpers import (
    APP_NAME,
    CERTS_NAME,
    DUMMY_NAME,
    KAFKA_CONTAINER,
    MANUAL_TLS_NAME,
    MTLS_NAME,
    REL_NAME_ADMIN,
    TLS_NAME,
    TLS_REQUIRER,
    ZK_NAME,
    check_hostname_verification,
    check_tls,
    copy_file_to_unit,
    create_test_topic,
    delete_pod,
    extract_ca,
    extract_private_key,
    get_active_brokers,
    get_address,
    get_kafka_zk_relation_data,
    get_mtls_nodeport,
    get_secret_by_label,
    get_unit_hostname,
    list_truststore_aliases,
    search_secrets,
    set_mtls_client_acls,
    set_tls_private_key,
    sign_manual_certs,
)

logger = logging.getLogger(__name__)


@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
async def test_deploy_tls(ops_test: OpsTest, kafka_charm, app_charm):
    tls_config = {"ca-common-name": "kafka"}

    await asyncio.gather(
        # FIXME (certs): Unpin the revision once the charm is fixed
        ops_test.model.deploy(
            TLS_NAME, channel="edge", config=tls_config, revision=163, trust=True
        ),
        ops_test.model.deploy(ZK_NAME, channel="3/edge", num_units=3, trust=True),
        ops_test.model.deploy(
            kafka_charm,
            application_name=APP_NAME,
            resources={"kafka-image": KAFKA_CONTAINER},
            config={
                "ssl_principal_mapping_rules": "RULE:^.*[Cc][Nn]=([a-zA-Z0-9.]*).*$/$1/L,DEFAULT",
                "expose_external": "nodeport",
            },
            trust=True,
        ),
    )
    async with ops_test.fast_forward(fast_interval="20s"):
        await ops_test.model.block_until(
            lambda: len(ops_test.model.applications[ZK_NAME].units) == 3
        )
        await asyncio.sleep(60)

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME, TLS_NAME], idle_period=30, timeout=2000, raise_on_error=False
    )

    assert ops_test.model.applications[ZK_NAME].status == "active"
    assert ops_test.model.applications[TLS_NAME].status == "active"

    await ops_test.model.integrate(TLS_NAME, ZK_NAME)

    # Relate Zookeeper to TLS
    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(
            apps=[TLS_NAME, ZK_NAME],
            idle_period=30,
            status="active",
            timeout=2000,
            raise_on_error=False,
        )


@pytest.mark.abort_on_fail
async def test_kafka_tls(ops_test: OpsTest, app_charm):
    """Tests TLS on Kafka.

    Relates Zookeper[TLS] with Kafka[Non-TLS]. This leads to a blocked status.
    Afterwards, relate Kafka to TLS operator, which unblocks the application.
    """
    # Relate Zookeeper[TLS] to Kafka[Non-TLS]
    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.integrate(ZK_NAME, APP_NAME)
        await ops_test.model.wait_for_idle(
            apps=[ZK_NAME], idle_period=15, timeout=1000, status="active"
        )

        # Unit is on 'blocked' but whole app is on 'waiting'
        assert ops_test.model.applications[APP_NAME].status in ["waiting", "blocked"]

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
    await ops_test.model.integrate(f"{APP_NAME}:{TLS_RELATION}", TLS_NAME)
    async with ops_test.fast_forward(fast_interval="20s"):
        await asyncio.sleep(60)

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME, TLS_NAME], idle_period=30, timeout=1200, status="active"
    )

    kafka_address = await get_address(ops_test=ops_test, app_name=APP_NAME)

    # Client port shouldn't be up before relating to client app.
    assert not check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    )

    await asyncio.gather(
        ops_test.model.deploy(
            app_charm, application_name=DUMMY_NAME, num_units=1, series="jammy", trust=True
        ),
    )
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, DUMMY_NAME], timeout=1000, idle_period=30, raise_on_error=False
    )

    # ensuring at least a few update-status
    await ops_test.model.integrate(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
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
    await ops_test.model.integrate(
        f"{APP_NAME}:{TRUSTED_CERTIFICATE_RELATION}", f"{MTLS_NAME}:{TLS_RELATION}"
    )

    # ensuring kafka broker restarts with new listeners
    async with ops_test.fast_forward(fast_interval="30s"):
        await asyncio.sleep(180)

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, MTLS_NAME], idle_period=180, timeout=2000, status="active"
    )

    # getting kafka ca and address
    broker_ca = extract_ca(ops_test=ops_test, unit_name=f"{APP_NAME}/0")

    address = await get_address(ops_test, app_name=APP_NAME)
    sasl_port = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    sasl_bootstrap_server = f"{address}:{sasl_port}"
    ssl_nodeport = get_mtls_nodeport(ops_test)

    # setting ACLs using normal sasl port
    await set_mtls_client_acls(ops_test, bootstrap_server=sasl_bootstrap_server)

    num_messages = 10

    # running mtls producer
    action = await ops_test.model.units.get(f"{DUMMY_NAME}/0").run_action(
        "run-mtls-producer",
        **{
            "mtls-nodeport": int(ssl_nodeport),
            "broker-ca": base64.b64encode(broker_ca.encode("utf-8")).decode("utf-8"),
            "num-messages": num_messages,
        },
    )

    response = await action.wait()

    assert response.results.get("success", None) == "TRUE"

    offsets_action = await ops_test.model.units.get(f"{DUMMY_NAME}/0").run_action(
        "get-offsets",
        **{
            "mtls-nodeport": int(ssl_nodeport),
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
        TLS_NAME, channel="stable", application_name="other-ca", revision=155
    )
    await ops_test.model.deploy(
        TLS_REQUIRER, channel="stable", application_name="other-req", revision=102
    )

    await ops_test.model.integrate("other-ca", "other-req")

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
    await ops_test.model.integrate(f"{APP_NAME}:{TRUSTED_CERTIFICATE_RELATION}", "other-op")

    await ops_test.model.wait_for_idle(
        apps=["other-op", APP_NAME], idle_period=60, timeout=2000, status="active"
    )

    address = await get_address(ops_test, app_name=APP_NAME, unit_num=0)
    sasl_port = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    sasl_bootstrap_server = f"{address}:{sasl_port}"
    ssl_port = SECURITY_PROTOCOL_PORTS["SSL", "SSL"].external
    ssl_bootstrap_server = f"{address}:{ssl_port}"

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
    await ops_test.model.remove_application("other-op", block_until_done=True)
    await ops_test.model.remove_application("other-req", block_until_done=True)
    tmp_dir.cleanup()


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
    await ops_test.model.applications[APP_NAME].scale(scale=3)
    logger.info("Scaling Kafka to 3 units")
    await ops_test.model.block_until(
        lambda: len(ops_test.model.applications[APP_NAME].units) == 3, timeout=2000
    )

    # Wait for model to settle
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", idle_period=40, timeout=2000, raise_on_error=False
    )

    async with ops_test.fast_forward(fast_interval="20s"):
        await asyncio.sleep(90)

    kafka_zk_relation_data = get_kafka_zk_relation_data(
        ops_test=ops_test,
        unit_name=f"{APP_NAME}/2",
        owner=ZK_NAME,
    )

    # can't use *-endpoints address from outside of K8s cluster, need to patch
    zookeeper_addresses = [
        await get_address(ops_test, app_name=ZK_NAME, unit_num=unit.name.split("/")[1])
        for unit in ops_test.model.applications[ZK_NAME].units
    ]
    kafka_zk_relation_data["endpoints"] = ",".join(zookeeper_addresses)

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
    remove_relation_cmd = f"remove-relation {APP_NAME} {DUMMY_NAME}"
    await ops_test.juju(*remove_relation_cmd.split(), check=True)

    await ops_test.model.wait_for_idle(apps=[APP_NAME], idle_period=30, timeout=1000)
    assert not check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    )


@pytest.mark.abort_on_fail
async def test_tls_removed(ops_test: OpsTest):
    await ops_test.model.remove_application(TLS_NAME, block_until_done=True)

    # ensuring enough update-status to unblock ZK
    async with ops_test.fast_forward(fast_interval="60s"):
        await asyncio.sleep(180)

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME],
        timeout=3600,
        idle_period=30,
        status="active",
        raise_on_error=False,
    )

    kafka_address = await get_address(ops_test=ops_test, app_name=APP_NAME)
    assert not check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    )


@pytest.mark.abort_on_fail
async def test_dns_certificate(ops_test: OpsTest):
    tls_config = {"ca-common-name": "kafka"}
    # re-set up TLS with DNS-only certs
    await ops_test.model.applications[APP_NAME].set_config(
        {"certificate_include_ip_sans": "false"}
    )

    await ops_test.model.deploy(
        TLS_NAME, channel="edge", config=tls_config, series="jammy", revision=163
    )

    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.integrate(ZK_NAME, TLS_NAME)
        await ops_test.model.integrate(f"{APP_NAME}:{TLS_RELATION}", TLS_NAME)
        await ops_test.model.wait_for_idle(
            apps=[ZK_NAME], idle_period=15, timeout=1000, status="active"
        )

    # ensuring at least a few update-status
    async with ops_test.fast_forward(fast_interval="20s"):
        await asyncio.sleep(60)

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME, TLS_NAME], idle_period=30, timeout=1200, status="active"
    )

    root_ca = get_secret_by_label(ops_test, label="ca-certificates", owner=TLS_NAME)[
        "ca-certificate"
    ]

    test_unit_name = ops_test.model.applications[APP_NAME].units[0].name
    test_unit_hostname = get_unit_hostname(ops_test=ops_test, unit_name=test_unit_name).strip()

    # copying file to container
    copy_file_to_unit(
        ops_test=ops_test,
        unit_name=test_unit_name,
        filename="rootca.pem",
        content=root_ca,
    )

    output = check_hostname_verification(
        ops_test=ops_test,
        hostname=test_unit_hostname,
        port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].internal,
        cafile_name="rootca.pem",
        unit_name=test_unit_name,
    )

    assert f"Verified peername: {test_unit_hostname}" in output

    # Cleanup, remove TLS relation and app
    await ops_test.model.remove_application(TLS_NAME, block_until_done=True)
    await ops_test.model.applications[APP_NAME].set_config({"certificate_include_ip_sans": "true"})

    async with ops_test.fast_forward(fast_interval="60s"):
        await asyncio.sleep(180)

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME],
        timeout=3600,
        idle_period=30,
        status="active",
        raise_on_error=False,
    )


@pytest.mark.abort_on_fail
@pytest.mark.unstable
async def test_pod_reschedule_tls(ops_test: OpsTest):
    delete_pod(ops_test, f"{APP_NAME}-0")

    async with ops_test.fast_forward(fast_interval="30s"):
        await asyncio.sleep(90)

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        idle_period=90,
        timeout=2000,
    )


@pytest.mark.abort_on_fail
async def test_manual_tls_chain(ops_test: OpsTest):
    await ops_test.model.deploy(MANUAL_TLS_NAME)

    await asyncio.gather(
        ops_test.model.integrate(f"{APP_NAME}:{TLS_RELATION}", MANUAL_TLS_NAME),
        ops_test.model.integrate(ZK_NAME, MANUAL_TLS_NAME),
    )

    # ensuring enough time for multiple rolling-restart with update-status
    async with ops_test.fast_forward(fast_interval="30s"):
        await asyncio.sleep(180)

    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, ZK_NAME, MANUAL_TLS_NAME], idle_period=30, timeout=1000
        )

    sign_manual_certs(ops_test)

    # verifying brokers + servers can communicate with one-another
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME, MANUAL_TLS_NAME], idle_period=30, timeout=1000
    )

    # verifying the chain is in there
    trusted_aliases = await list_truststore_aliases(ops_test)

    assert len(trusted_aliases) == 3  # cert, intermediate, rootca

    # verifying TLS is enabled and working
    kafka_address = await get_address(ops_test=ops_test, app_name=APP_NAME)
    assert check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].internal
    )
