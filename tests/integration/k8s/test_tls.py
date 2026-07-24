#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
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
from single_kernel_kafka.core.literals import (
    CERTIFICATE_TRANSFER_RELATION,
    SECURITY_PROTOCOL_PORTS,
    TLS_RELATION,
)

from integration.k8s.helpers import sign_manual_certs
from integration.k8s.helpers.jubilant import all_active_idle, deploy_cluster, fast_forward
from integration.k8s.helpers.legacy import (
    APP_NAME,
    DUMMY_NAME,
    MANUAL_TLS_NAME,
    REL_NAME_PRODUCER,
    TLS_NAME,
    TLS_REQUIRER,
    check_socket,
    check_tls,
    create_test_topic,
    delete_pod,
    extract_private_key,
    get_actual_tls_private_key,
    get_address,
    list_truststore_aliases,
    remove_tls_private_key,
    search_secrets,
    set_tls_private_key,
    update_tls_private_key,
)

logger = logging.getLogger(__name__)


def test_deploy_tls(juju: jubilant.Juju, kafka_charm, kraft_mode, kafka_apps):
    tls_config = {"ca-common-name": "kafka"}

    juju.deploy(TLS_NAME, channel="1/stable", config=tls_config, trust=True)
    deploy_cluster(
        juju=juju,
        charm=kafka_charm,
        kraft_mode=kraft_mode,
        # config_broker={"expose-external": "nodeport"},
    )
    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, TLS_NAME),
        delay=3,
        successes=10,
        timeout=2000,
    )

    status = juju.status()
    assert status.apps[APP_NAME].app_status.current == "active"
    assert status.apps[TLS_NAME].app_status.current == "active"


def test_kafka_tls(juju: jubilant.Juju, app_charm, kafka_apps):
    """Tests TLS on Kafka.

    Relates Zookeper[TLS] with Kafka[Non-TLS]. This leads to a blocked status.
    Afterwards, relate Kafka to TLS operator, which unblocks the application.
    """
    # ensuring at least a few update-status
    juju.integrate(f"{APP_NAME}:{TLS_RELATION}", TLS_NAME)
    with fast_forward(juju, fast_interval="20s"):
        time.sleep(60)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, TLS_NAME),
        delay=3,
        successes=10,
        timeout=1200,
    )

    kafka_address = get_address(juju=juju, app_name=APP_NAME)

    # Client port shouldn't be up before relating to client app.
    assert not check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    )

    juju.deploy(app_charm, app=DUMMY_NAME, num_units=1, base="ubuntu@22.04", trust=True)
    juju.wait(
        lambda status: jubilant.all_agents_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=1000,
    )

    # ensuring at least a few update-status
    juju.integrate(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_PRODUCER}")
    with fast_forward(juju, fast_interval="20s"):
        time.sleep(60)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=600,
    )

    assert check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    )


def test_set_tls_private_key(juju: jubilant.Juju):
    # 1. First test the setting of new PKs on an existing cluster
    old_pks = set()
    secret: dict[str, PrivateKey] = {}
    for unit in juju.status().apps[APP_NAME].units:
        old_pks.add(extract_private_key(juju, unit))
        secret[unit.replace("/", "-")] = generate_private_key()

    set_tls_private_key(juju, secret=secret)

    with fast_forward(juju, fast_interval="60s"):
        juju.wait(
            lambda status: all_active_idle(status, APP_NAME, DUMMY_NAME, TLS_NAME),
            delay=3,
            successes=10,
            timeout=600,
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

    with fast_forward(juju, fast_interval="60s"):
        juju.wait(
            lambda status: all_active_idle(status, APP_NAME, DUMMY_NAME, TLS_NAME),
            delay=3,
            successes=10,
            timeout=600,
        )

    updated_secret_pk = extract_private_key(
        juju, removed_secret_unit_name.replace(f"{APP_NAME}-", f"{APP_NAME}/")
    )
    updated_actual_pk = get_actual_tls_private_key(
        juju, removed_secret_unit_name.replace(f"{APP_NAME}-", f"{APP_NAME}/")
    )

    assert updated_secret_pk == updated_actual_pk
    assert updated_secret_pk != removed_secret_tls_pk

    # 3. Now test the removal of the PK secret config entirely
    remove_tls_private_key(juju)

    with fast_forward(juju, fast_interval="60s"):
        juju.wait(
            lambda status: all_active_idle(status, APP_NAME, DUMMY_NAME, TLS_NAME),
            delay=3,
            successes=10,
            timeout=600,
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


def test_mtls(juju: jubilant.Juju, kafka_apps):
    # creating the signed external cert on the unit
    response = juju.run(f"{DUMMY_NAME}/0", "create-certificate", wait=1800)

    with fast_forward(juju, fast_interval="120s"):
        juju.wait(
            lambda status: all_active_idle(status, APP_NAME, DUMMY_NAME),
            delay=3,
            successes=10,
            timeout=600,
        )

    num_messages = 10
    # running mtls producer
    response = juju.run(
        f"{DUMMY_NAME}/0",
        "run-mtls-producer",
        params={"num-messages": num_messages},
    )

    assert response.results.get("success", None) == "TRUE"

    response = juju.run(
        f"{DUMMY_NAME}/0",
        "get-offsets",
    )

    topic_name, min_offset, max_offset = response.results["output"].strip().split(":")

    assert topic_name == "test-topic"
    assert min_offset == "0"
    assert max_offset == str(num_messages)


def test_certificate_transfer(juju: jubilant.Juju, kafka_apps):
    """Tests truststore live reload functionality using kafka-python client."""
    requirer = "other-req/0"
    test_msg = {"test": 123456}
    juju.config(APP_NAME, {"expose-external": "nodeport"})

    juju.deploy(
        TLS_NAME,
        channel="1/stable",
        app="other-ca",
    )
    juju.deploy(TLS_REQUIRER, channel="stable", app="other-req", revision=102)

    juju.integrate("other-ca", "other-req")

    juju.wait(
        lambda status: all_active_idle(status, "other-ca", "other-req"),
        delay=3,
        successes=20,
        timeout=2000,
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

    with fast_forward(juju, fast_interval="60s"):
        time.sleep(120)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=3,
        successes=10,
        timeout=900,
    )

    address = get_address(juju, app_name=APP_NAME, unit_num=0)
    sasl_port = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].internal
    sasl_bootstrap_server = f"{address}:{sasl_port}"
    ssl_port = SECURITY_PROTOCOL_PORTS["SSL", "SSL"].external
    ssl_bootstrap_server = f"{address}:{ssl_port}"

    # create `test` topic and set ACLs
    create_test_topic(juju, bootstrap_server=sasl_bootstrap_server)

    # Wait for eventual broker restart, which opens client ports.
    with fast_forward(juju, fast_interval="60s"):
        while not check_socket(address, ssl_port):
            time.sleep(30)

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
    juju.wait(lambda status: "other-ca" not in status.apps and "other-req" not in status.apps)
    tmp_dir.cleanup()


def test_kafka_tls_scaling(juju: jubilant.Juju, kafka_apps):
    """Scale the application while using TLS to check that new units will configure correctly."""
    juju.cli("scale-application", APP_NAME, "3")
    logger.info("Scaling Kafka to 3 units")

    # Wait for model to settle
    juju.wait(
        lambda status: len(status.apps[APP_NAME].units) == 3
        and all_active_idle(status, *kafka_apps),
        delay=3,
        successes=15,
        timeout=2000,
    )

    with fast_forward(juju, fast_interval="20s"):
        time.sleep(90)

    # TODO

    kafka_address = get_address(juju=juju, app_name=APP_NAME, unit_num=2)
    assert check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    )


def test_mtls_broken(juju: jubilant.Juju, kafka_apps):
    # remove relation and check connection again
    juju.remove_relation(APP_NAME, DUMMY_NAME)

    # ensuring enough update-status
    with fast_forward(juju, fast_interval="60s"):
        time.sleep(120)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=15,
        timeout=2000,
    )

    for unit_num in range(len(juju.status().apps[APP_NAME].units)):
        kafka_address = get_address(juju=juju, app_name=APP_NAME, unit_num=unit_num)
        assert not check_tls(
            ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
        )
        assert not check_tls(ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SSL", "SSL"].client)


def test_tls_removed(juju: jubilant.Juju, kafka_apps):
    juju.remove_relation(f"{APP_NAME}:certificates", f"{TLS_NAME}:certificates")

    # ensuring enough update-status
    with fast_forward(juju, fast_interval="60s"):
        time.sleep(180)

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


@pytest.mark.unstable
def test_pod_reschedule_tls(juju: jubilant.Juju, kafka_apps):
    delete_pod(juju, f"{APP_NAME}-0")

    with fast_forward(juju, fast_interval="30s"):
        time.sleep(90)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=3,
        successes=30,
        timeout=2000,
    )


def test_manual_tls_chain(juju: jubilant.Juju, kafka_apps):
    assert juju.model
    juju.deploy(MANUAL_TLS_NAME)

    juju.integrate(f"{APP_NAME}:{TLS_RELATION}", MANUAL_TLS_NAME)

    # ensuring enough time for multiple rolling-restart with update-status
    with fast_forward(juju, fast_interval="30s"):
        time.sleep(180)

    with fast_forward(juju, fast_interval="120s"):
        juju.wait(
            lambda status: jubilant.all_agents_idle(status, *kafka_apps, MANUAL_TLS_NAME),
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
