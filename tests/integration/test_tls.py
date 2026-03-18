#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import base64
import json
import logging
import os
import tempfile
from time import sleep

import kafka
import pytest
from charms.tls_certificates_interface.v3.tls_certificates import generate_private_key

from literals import (
    REL_NAME,
    SECURITY_PROTOCOL_PORTS,
    TLS_RELATION,
    TRUSTED_CERTIFICATE_RELATION,
    ZK,
)

from .adapters import JujuFixture, gather
from .helpers import (
    APP_NAME,
    REL_NAME_ADMIN,
    check_hostname_verification,
    check_tls,
    copy_file_to_unit,
    create_test_topic,
    extract_ca,
    extract_private_key,
    get_active_brokers,
    get_address,
    get_kafka_zk_relation_data,
    get_secret_by_label,
    get_unit_hostname,
    list_truststore_aliases,
    search_secrets,
    set_mtls_client_acls,
    set_tls_private_key,
    sign_manual_certs,
)
from .test_charm import DUMMY_NAME

logger = logging.getLogger(__name__)

TLS_NAME = "self-signed-certificates"
CERTS_NAME = "tls-certificates-operator"
MTLS_NAME = "mtls"
TLS_REQUIRER = "tls-certificates-requirer"
MANUAL_TLS_NAME = "manual-tls-certificates"
TLS_CONFIG = {"ca-common-name": "kafka"}


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
def test_deploy_tls(juju: JujuFixture, kafka_charm):
    gather(
        # FIXME (certs): Unpin the revision once the charm is fixed
        juju.ext.model.deploy(
            TLS_NAME, channel="edge", config=TLS_CONFIG, series="jammy", revision=163
        ),
        juju.ext.model.deploy(ZK, channel="edge", series="jammy", application_name=ZK),
        juju.ext.model.deploy(
            kafka_charm,
            application_name=APP_NAME,
            series="jammy",
            config={
                "ssl_principal_mapping_rules": "RULE:^.*[Cc][Nn]=([a-zA-Z0-9.]*).*$/$1/L,DEFAULT"
            },
        ),
    )
    juju.ext.model.block_until(lambda: len(juju.ext.model.applications[ZK].units) == 1)
    juju.ext.model.wait_for_idle(apps=[APP_NAME, ZK, TLS_NAME], idle_period=15, timeout=1800)

    assert juju.ext.model.applications[ZK].status == "active"
    assert juju.ext.model.applications[TLS_NAME].status == "active"

    juju.ext.model.add_relation(TLS_NAME, ZK)

    # Relate Zookeeper to TLS
    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(apps=[TLS_NAME, ZK], idle_period=30, status="active")


@pytest.mark.abort_on_fail
def test_kafka_tls(juju: JujuFixture, app_charm):
    """Tests TLS on Kafka.

    Relates Zookeper[TLS] with Kafka[Non-TLS]. This leads to a blocked status.
    Afterwards, relate Kafka to TLS operator, which unblocks the application.
    """
    # Relate Zookeeper[TLS] to Kafka[Non-TLS]
    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.add_relation(ZK, APP_NAME)
        juju.ext.model.wait_for_idle(apps=[ZK], idle_period=15, timeout=1000, status="active")

        # Unit is on 'blocked' but whole app is on 'waiting'
        assert juju.ext.model.applications[APP_NAME].status == "blocked"

    # Set a custom private key, by running set-tls-private-key action with no parameters,
    # as this will generate a random one
    num_unit = 0
    set_tls_private_key(juju)

    # Extract the key
    private_key = extract_private_key(
        juju=juju,
        unit_name=f"{APP_NAME}/{num_unit}",
    )

    # ensuring at least a few update-status
    juju.ext.model.add_relation(f"{APP_NAME}:{TLS_RELATION}", TLS_NAME)
    with juju.ext.fast_forward(fast_interval="20s"):
        sleep(60)

    juju.ext.model.wait_for_idle(
        apps=[APP_NAME, ZK, TLS_NAME], idle_period=30, timeout=1200, status="active"
    )

    kafka_address = get_address(juju=juju, app_name=APP_NAME)

    assert not check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    )

    gather(
        juju.ext.model.deploy(app_charm, application_name=DUMMY_NAME, num_units=1, series="jammy"),
    )
    juju.ext.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME], timeout=1000, idle_period=30)

    # ensuring at least a few update-status
    juju.ext.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    with juju.ext.fast_forward(fast_interval="20s"):
        sleep(60)

    juju.ext.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME], idle_period=30, status="active")

    assert check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    )

    # Rotate credentials
    new_private_key = generate_private_key().decode("utf-8")

    set_tls_private_key(juju, key=new_private_key)

    # ensuring key event actually runs
    with juju.ext.fast_forward(fast_interval="10s"):
        sleep(60)

    # Extract the key
    private_key_2 = extract_private_key(
        juju=juju,
        unit_name=f"{APP_NAME}/{num_unit}",
    )

    assert private_key != private_key_2
    assert private_key_2 == new_private_key


@pytest.mark.abort_on_fail
def test_mtls(juju: JujuFixture):
    # creating the signed external cert on the unit
    action = juju.ext.model.units.get(f"{DUMMY_NAME}/0").run_action("create-certificate")
    response = action.wait()
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
    juju.ext.model.deploy(
        CERTS_NAME, channel="stable", config=tls_config, series="jammy", application_name=MTLS_NAME
    )
    juju.ext.model.wait_for_idle(apps=[MTLS_NAME], timeout=1000, idle_period=15)
    juju.ext.model.add_relation(
        f"{APP_NAME}:{TRUSTED_CERTIFICATE_RELATION}", f"{MTLS_NAME}:{TLS_RELATION}"
    )
    juju.ext.model.wait_for_idle(
        apps=[APP_NAME, MTLS_NAME], idle_period=60, timeout=2000, status="active"
    )

    # getting kafka ca and address
    broker_ca = extract_ca(juju=juju, unit_name=f"{APP_NAME}/0")

    address = get_address(juju, app_name=APP_NAME)
    ssl_port = SECURITY_PROTOCOL_PORTS["SSL", "SSL"].client
    sasl_port = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    ssl_bootstrap_server = f"{address}:{ssl_port}"
    sasl_bootstrap_server = f"{address}:{sasl_port}"

    # setting ACLs using normal sasl port
    set_mtls_client_acls(juju, bootstrap_server=sasl_bootstrap_server)

    num_messages = 10

    # running mtls producer
    action = juju.ext.model.units.get(f"{DUMMY_NAME}/0").run_action(
        "run-mtls-producer",
        **{
            "bootstrap-server": ssl_bootstrap_server,
            "broker-ca": base64.b64encode(broker_ca.encode("utf-8")).decode("utf-8"),
            "num-messages": num_messages,
        },
    )

    response = action.wait()

    assert response.results.get("success", None) == "TRUE"

    offsets_action = juju.ext.model.units.get(f"{DUMMY_NAME}/0").run_action(
        "get-offsets",
        **{
            "bootstrap-server": ssl_bootstrap_server,
        },
    )

    response = offsets_action.wait()

    topic_name, min_offset, max_offset = response.results["output"].strip().split(":")

    assert topic_name == "TEST-TOPIC"
    assert min_offset == "0"
    assert max_offset == str(num_messages)


@pytest.mark.abort_on_fail
def test_truststore_live_reload(juju: JujuFixture):
    """Tests truststore live reload functionality using kafka-python client."""
    requirer = "other-req/0"
    test_msg = {"test": 123456}

    juju.ext.model.deploy(TLS_NAME, channel="stable", application_name="other-ca", revision=155)
    juju.ext.model.deploy(
        TLS_REQUIRER, channel="stable", application_name="other-req", revision=102
    )

    juju.ext.model.add_relation("other-ca", "other-req")

    juju.ext.model.wait_for_idle(
        apps=["other-ca", "other-req"], idle_period=60, timeout=2000, status="active"
    )

    # retrieve required certificates and private key from secrets
    local_store = {
        "private_key": search_secrets(juju=juju, owner=requirer, search_key="private-key"),
        "cert": search_secrets(juju=juju, owner=requirer, search_key="certificate"),
        "ca_cert": search_secrets(juju=juju, owner=requirer, search_key="ca-certificate"),
        "broker_ca": search_secrets(juju=juju, owner=f"{APP_NAME}/0", search_key="ca-cert"),
    }

    certs_operator_config = {
        "generate-self-signed-certificates": "false",
        "certificate": base64.b64encode(local_store["cert"].encode("utf-8")).decode("utf-8"),
        "ca-certificate": base64.b64encode(local_store["ca_cert"].encode("utf-8")).decode("utf-8"),
    }

    juju.ext.model.deploy(
        CERTS_NAME,
        channel="stable",
        series="jammy",
        application_name="other-op",
        config=certs_operator_config,
    )

    juju.ext.model.wait_for_idle(apps=["other-op"], idle_period=60, timeout=2000, status="active")

    # We don't expect a broker restart here because of truststore live reload
    juju.ext.model.add_relation(f"{APP_NAME}:{TRUSTED_CERTIFICATE_RELATION}", "other-op")

    juju.ext.model.wait_for_idle(
        apps=["other-op", APP_NAME], idle_period=60, timeout=2000, status="active"
    )

    address = get_address(juju, app_name=APP_NAME, unit_num=0)
    ssl_port = SECURITY_PROTOCOL_PORTS["SSL", "SSL"].client
    ssl_bootstrap_server = f"{address}:{ssl_port}"
    sasl_port = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    sasl_bootstrap_server = f"{address}:{sasl_port}"

    # create `test` topic and set ACLs
    create_test_topic(juju, bootstrap_server=sasl_bootstrap_server)

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
    juju.ext.model.remove_application("other-ca", block_until_done=True)
    juju.ext.model.remove_application("other-op", block_until_done=True)
    juju.ext.model.remove_application("other-req", block_until_done=True)
    tmp_dir.cleanup()


@pytest.mark.abort_on_fail
def test_mtls_broken(juju: JujuFixture):
    juju.ext.model.remove_application(MTLS_NAME, block_until_done=True)
    juju.ext.model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        idle_period=30,
        timeout=2000,
    )


@pytest.mark.abort_on_fail
def test_kafka_tls_scaling(juju: JujuFixture):
    """Scale the application while using TLS to check that new units will configure correctly."""
    juju.ext.model.applications[APP_NAME].add_units(count=2)
    juju.ext.model.block_until(
        lambda: len(juju.ext.model.applications[APP_NAME].units) == 3, timeout=1000
    )

    # Wait for model to settle
    juju.ext.model.wait_for_idle(
        apps=[APP_NAME], status="active", idle_period=40, timeout=1000, raise_on_error=False
    )

    kafka_zk_relation_data = get_kafka_zk_relation_data(
        unit_name=f"{APP_NAME}/2",
        juju=juju,
        owner=ZK,
    )
    active_brokers = get_active_brokers(config=kafka_zk_relation_data)
    chroot = kafka_zk_relation_data.get("database", kafka_zk_relation_data.get("chroot", ""))
    assert f"{chroot}/brokers/ids/0" in active_brokers
    assert f"{chroot}/brokers/ids/1" in active_brokers
    assert f"{chroot}/brokers/ids/2" in active_brokers

    kafka_address = get_address(juju=juju, app_name=APP_NAME, unit_num=2)
    assert check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    )

    # remove relation and check connection again
    juju.ext.model.applications[APP_NAME].remove_relation(
        f"{APP_NAME}:{REL_NAME}", f"{DUMMY_NAME}:{REL_NAME_ADMIN}"
    )
    juju.ext.model.wait_for_idle(apps=[APP_NAME])
    assert not check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    )


@pytest.mark.abort_on_fail
def test_tls_removed(juju: JujuFixture):
    juju.ext.model.remove_application(TLS_NAME, block_until_done=True)
    juju.ext.model.wait_for_idle(
        apps=[APP_NAME, ZK], timeout=3600, idle_period=30, status="active", raise_on_error=False
    )

    kafka_address = get_address(juju=juju, app_name=APP_NAME)
    assert not check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    )

    # check proper cleanup of TLS-related files.
    for unit in juju.ext.model.applications[APP_NAME].units:
        ret, stdout, _ = juju.old_cli(
            "ssh", unit.name, "sudo ls /var/snap/charmed-kafka/current/etc/kafka"
        )
        assert not ret
        file_extensions = {f.split(".")[-1] for f in stdout.split() if f}
        logging.info(f"{', '.join(file_extensions)} files found on {unit.name}")
        assert not {"pem", "key", "p12", "jks"} & file_extensions


@pytest.mark.abort_on_fail
def test_dns_certificate(juju: JujuFixture):
    # re-set up TLS with DNS-only certs
    juju.ext.model.applications[APP_NAME].set_config({"certificate_include_ip_sans": "false"})

    juju.ext.model.deploy(
        TLS_NAME, channel="edge", config=TLS_CONFIG, series="jammy", revision=163
    )

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.add_relation(ZK, TLS_NAME)
        juju.ext.model.add_relation(f"{APP_NAME}:{TLS_RELATION}", TLS_NAME)
        juju.ext.model.wait_for_idle(apps=[ZK], idle_period=15, timeout=1000, status="active")

    # ensuring at least a few update-status
    with juju.ext.fast_forward(fast_interval="20s"):
        sleep(60)

    juju.ext.model.wait_for_idle(
        apps=[APP_NAME, ZK, TLS_NAME], idle_period=30, timeout=1200, status="active"
    )

    root_ca = get_secret_by_label(juju, label="ca-certificates", owner=TLS_NAME)["ca-certificate"]

    test_unit_name = juju.ext.model.applications[APP_NAME].units[0].name
    test_unit_hostname = get_unit_hostname(juju=juju, unit_name=test_unit_name).strip()

    # copying file to LXD container with DNS
    copy_file_to_unit(
        juju=juju,
        unit_name=test_unit_name,
        filename="rootca.pem",
        content=root_ca,
    )

    output = check_hostname_verification(
        juju=juju,
        hostname=test_unit_hostname,
        port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].internal,
        cafile_name="rootca.pem",
        unit_name=test_unit_name,
    )

    assert f"Verified peername: {test_unit_hostname}" in output


# TODO: this test tends to be really flaky and needs treatment.
@pytest.mark.skipif(
    os.environ.get("CI") is not None, reason="Flaky on CI, passes 1 out of 3 times on average."
)
@pytest.mark.abort_on_fail
def test_manual_tls_chain(juju: JujuFixture):
    juju.ext.model.deploy(MANUAL_TLS_NAME)

    gather(
        juju.ext.model.add_relation(f"{APP_NAME}:{TLS_RELATION}", MANUAL_TLS_NAME),
        juju.ext.model.add_relation(ZK, MANUAL_TLS_NAME),
    )

    # ensuring enough time for multiple rolling-restart with update-status
    with juju.ext.fast_forward(fast_interval="30s"):
        sleep(180)

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, ZK, MANUAL_TLS_NAME],
            idle_period=30,
            timeout=1000,
            raise_on_error=False,
        )

    sign_manual_certs(juju)

    # verifying brokers + servers can communicate with one-another
    juju.ext.model.wait_for_idle(
        apps=[APP_NAME, ZK, MANUAL_TLS_NAME],
        idle_period=30,
        timeout=1000,
        raise_on_error=False,
        status="active",
    )

    # verifying the chain is in there
    trusted_aliases = list_truststore_aliases(juju)

    assert len(trusted_aliases) == 3  # cert, intermediate, rootca

    # verifying TLS is enabled and working
    kafka_address = get_address(juju=juju, app_name=APP_NAME)
    assert check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].internal
    )
