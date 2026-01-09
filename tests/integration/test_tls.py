#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import os
import tempfile
import time

import jubilant
import kafka
import pytest
from charms.tls_certificates_interface.v4.tls_certificates import PrivateKey, generate_private_key

from integration.helpers import REL_NAME_PRODUCER, sign_manual_certs
from integration.helpers.jubilant import (
    APP_NAME,
    BASE,
    all_active_idle,
    check_tls,
    create_test_topic,
    deploy_cluster,
    extract_private_key,
    get_actual_tls_private_key,
    get_address,
    get_provider_data,
    list_truststore_aliases,
    remove_tls_private_key,
    search_secrets,
    set_tls_private_key,
    update_tls_private_key,
)
from literals import (
    CERTIFICATE_TRANSFER_RELATION,
    REL_NAME,
    SECURITY_PROTOCOL_PORTS,
    TLS_RELATION,
)

from .test_charm import DUMMY_NAME

logger = logging.getLogger(__name__)

TLS_NAME = "self-signed-certificates"
CERTS_NAME = "tls-certificates-operator"
TLS_REQUIRER = "tls-certificates-requirer"
MANUAL_TLS_NAME = "manual-tls-certificates"


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
def test_deploy_tls(juju: jubilant.Juju, kafka_charm, kraft_mode, kafka_apps):
    tls_config = {"ca-common-name": "kafka"}

    juju.deploy(TLS_NAME, channel="1/stable", config=tls_config)
    deploy_cluster(
        juju=juju,
        charm=kafka_charm,
        kraft_mode=kraft_mode,
        config_broker={
            "ssl-principal-mapping-rules": "RULE:^.*[Cc][Nn]=([a-zA-Z0-9.]*).*$/$1/L,DEFAULT"
        },
    )

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, TLS_NAME),
        delay=3,
        successes=10,
        timeout=1800,
    )


@pytest.mark.abort_on_fail
def test_kafka_tls(juju: jubilant.Juju, app_charm, kafka_apps):
    """Tests TLS on Kafka."""
    # ensuring at least a few update-status
    juju.integrate(f"{APP_NAME}:{TLS_RELATION}", TLS_NAME)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, TLS_NAME),
        delay=3,
        successes=20,
        timeout=900,
    )

    kafka_address = get_address(juju=juju, app_name=APP_NAME)

    assert not check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    )

    juju.deploy(app_charm, app=DUMMY_NAME, num_units=1, base=BASE)
    juju.integrate(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_PRODUCER}")

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=20,
        timeout=1000,
    )

    assert check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    )


@pytest.mark.abort_on_fail
def test_set_tls_private_key(juju: jubilant.Juju):
    juju.cli("model-config", "update-status-hook-interval=60s")

    # 1. First test the setting of new PKs on an existing cluster
    old_pks = set()
    secret: dict[str, PrivateKey] = {}
    for unit in juju.status().apps[APP_NAME].units:
        old_pks.add(extract_private_key(juju, unit))
        secret[unit.replace("/", "-")] = generate_private_key()

    set_tls_private_key(juju, secret=secret)

    juju.wait(
        lambda status: all_active_idle(status, APP_NAME, DUMMY_NAME, TLS_NAME),
        delay=3,
        successes=10,
        timeout=900,
    )

    new_pks = set()
    actual_pks = set()
    for unit in juju.status().apps[APP_NAME].units:
        new_pks.add(extract_private_key(juju, unit))
        actual_pks.add(get_actual_tls_private_key(juju, unit))

    assert new_pks.isdisjoint(old_pks)  # all pks changed in secret data
    assert new_pks == actual_pks  # all pks actually written to charm

    # 2. Now test the updating a new PK on a single unit
    removed_secret_unit_name, removed_secret_tls_pk = secret.popitem()  # getting random unit
    secret.update({removed_secret_unit_name: generate_private_key()})  # replacing cert

    update_tls_private_key(juju, secret=secret)

    juju.wait(
        lambda status: all_active_idle(status, APP_NAME, DUMMY_NAME, TLS_NAME),
        delay=3,
        successes=10,
        timeout=900,
    )

    updated_secret_pk = extract_private_key(juju, removed_secret_unit_name.replace("-", "/"))
    updated_actual_pk = get_actual_tls_private_key(
        juju, removed_secret_unit_name.replace("-", "/")
    )

    assert updated_secret_pk == updated_actual_pk
    assert updated_secret_pk != removed_secret_tls_pk

    # 3. Now test the removal of the PK secret config entirely
    remove_tls_private_key(juju)

    juju.wait(
        lambda status: all_active_idle(status, APP_NAME, DUMMY_NAME, TLS_NAME),
        delay=3,
        successes=10,
        timeout=900,
    )

    post_removed_pks = set()
    post_removed_actual_pks = set()
    for unit in juju.status().apps[APP_NAME].units:
        post_removed_pks.add(extract_private_key(juju, unit))
        post_removed_actual_pks.add(get_actual_tls_private_key(juju, unit))

    assert post_removed_pks == post_removed_actual_pks

    pre_pks = new_pks | actual_pks | {updated_secret_pk, updated_actual_pk}
    post_pks = post_removed_pks | post_removed_actual_pks

    assert post_pks.isdisjoint(pre_pks)  # checking every post-secret-removed pk is brand new


@pytest.mark.abort_on_fail
def test_mtls(juju: jubilant.Juju):
    # creating the signed external cert on the unit
    _ = juju.run(f"{DUMMY_NAME}/0", "create-certificate")

    juju.wait(
        lambda status: all_active_idle(status, APP_NAME, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=900,
    )

    # run mtls producer
    num_messages = 10
    response = juju.run(
        f"{DUMMY_NAME}/0",
        "run-mtls-producer",
        params={"num-messages": num_messages},
    )
    assert response.results.get("success", None) == "TRUE"

    provider_data = get_provider_data(
        juju.model,
        owner=DUMMY_NAME,
        unit_name=f"{DUMMY_NAME}/0",
        relation_interface=REL_NAME_PRODUCER,
    )

    response = juju.run(
        f"{DUMMY_NAME}/0",
        "get-offsets",
        params={
            "bootstrap-server": provider_data["endpoints"],
        },
    )
    topic_name, min_offset, max_offset = response.results["output"].strip().split(":")

    assert topic_name == "test-topic"
    assert min_offset == "0"
    assert max_offset == str(num_messages)


@pytest.mark.abort_on_fail
def test_certificate_transfer(juju: jubilant.Juju, kafka_apps):
    """Tests truststore live reload functionality using kafka-python client."""
    requirer = "other-req/0"
    test_msg = {"test": 123456}

    juju.deploy(
        TLS_NAME,
        app="other-ca",
        channel="1/stable",
    )
    juju.deploy(TLS_REQUIRER, channel="stable", app="other-req", revision=102)
    juju.integrate("other-ca", "other-req")

    juju.wait(
        lambda status: all_active_idle(status, "other-ca", "other-req"),
        delay=3,
        successes=10,
        timeout=900,
    )

    # retrieve required certificates and private key from secrets
    local_store = {
        "private_key": search_secrets(juju=juju, owner=requirer, search_key="private-key"),
        "cert": search_secrets(juju=juju, owner=requirer, search_key="certificate"),
        "ca_cert": search_secrets(juju=juju, owner=requirer, search_key="ca-certificate"),
        "broker_ca": search_secrets(juju=juju, owner=f"{APP_NAME}/0", search_key="client-ca-cert"),
    }

    # Transfer other-ca's CA certificate via the client-cas relation
    # We don't expect a broker restart here because of truststore live reload
    juju.integrate(f"{APP_NAME}:{CERTIFICATE_TRANSFER_RELATION}", "other-ca:send-ca-cert")

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=3,
        successes=20,
        timeout=2000,
    )

    address = get_address(juju, app_name=APP_NAME, unit_num=0)
    ssl_port = SECURITY_PROTOCOL_PORTS["SSL", "SSL"].client
    ssl_bootstrap_server = f"{address}:{ssl_port}"
    sasl_port = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].internal
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
        "api_version": (2, 6),
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
    juju.remove_application("other-ca")
    juju.remove_application("other-req")
    time.sleep(180)
    tmp_dir.cleanup()


@pytest.mark.abort_on_fail
def test_kafka_tls_scaling(juju: jubilant.Juju, kafka_apps):
    """Scale the application while using TLS to check that new units will configure correctly."""
    juju.add_unit(APP_NAME, num_units=2)
    time.sleep(60)

    # Wait for model to settle
    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=2,
        successes=20,
        timeout=1800,
    )

    kafka_address = get_address(juju=juju, app_name=APP_NAME, unit_num=2)
    assert check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    )


@pytest.mark.abort_on_fail
def test_mtls_broken(juju: jubilant.Juju, kafka_apps):
    # remove client relation and check connection
    juju.remove_relation(f"{APP_NAME}:{REL_NAME}", f"{DUMMY_NAME}:{REL_NAME_PRODUCER}")

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=3,
        successes=20,
        timeout=900,
    )

    for unit in juju.status().apps[APP_NAME].units:
        unit_num = int(unit.split("/")[1])
        kafka_address = get_address(juju=juju, app_name=APP_NAME, unit_num=unit_num)
        assert not check_tls(
            ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
        )
        assert not check_tls(ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SSL", "SSL"].client)


@pytest.mark.abort_on_fail
def test_tls_removed(juju: jubilant.Juju, kafka_apps):
    juju.remove_application(TLS_NAME)
    time.sleep(60)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=3,
        successes=10,
        timeout=3600,
    )

    kafka_address = get_address(juju=juju, app_name=APP_NAME)
    assert not check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    )

    # check proper cleanup of TLS-related files.
    for unit in juju.status().apps[APP_NAME].units:
        ret, stdout, _ = juju.cli(
            "ssh", unit.name, "sudo ls /var/snap/charmed-kafka/current/etc/kafka"
        )
        assert not ret
        file_extensions = {
            f.split(".")[-1] for f in stdout.split() if f and f.startswith("client-")
        }
        logging.info(f"CLIENT TLS: {', '.join(file_extensions)} files found on {unit.name}")
        assert not {"pem", "key", "p12", "jks"} & file_extensions

        # peer TLS artifacts should remain intact.
        file_extensions = {f.split(".")[-1] for f in stdout.split() if f and f.startswith("peer-")}
        logging.info(f"PEER TLS: {', '.join(file_extensions)} files found on {unit.name}")
        assert {"pem", "key", "p12", "jks"} & file_extensions


@pytest.mark.abort_on_fail
def test_manual_tls_chain(juju: jubilant.Juju, kafka_apps):
    juju.deploy(MANUAL_TLS_NAME)

    juju.integrate(f"{APP_NAME}:{TLS_RELATION}", MANUAL_TLS_NAME)

    # ensuring enough time for multiple rolling-restart with update-status
    time.sleep(180)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, MANUAL_TLS_NAME),
        delay=3,
        successes=10,
        timeout=1000,
    )

    sign_manual_certs(juju.model)

    # verifying brokers + servers can communicate with one-another
    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, MANUAL_TLS_NAME),
        delay=3,
        successes=10,
        timeout=1000,
    )

    # verifying the chain is in there
    trusted_aliases = list_truststore_aliases(juju)

    assert len(trusted_aliases) == 3  # cert, intermediate, rootca

    # verifying TLS is enabled and working
    kafka_address = get_address(juju=juju, app_name=APP_NAME)
    assert check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].internal
    )
