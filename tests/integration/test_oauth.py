#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import jubilant
import kafka
import pytest
from kafka.errors import TopicAuthorizationFailedError

from integration.helpers import (
    APP_NAME,
    get_controller_name,
    use_controller,
)
from integration.helpers.jubilant import (
    all_active_idle,
    deploy_cluster,
    get_unit_ipv4_address,
)
from integration.helpers.oauth import (
    CORE_MODEL,
    IAM_APPS,
    IAM_MODEL,
    SimpleTokenProvider,
    create_oauth_client,
    deploy_identity_platform,
    prepare_cli_client,
)
from integration.helpers.pytest_operator import check_socket
from literals import SECURITY_PROTOCOL_PORTS, TLS_RELATION

logger = logging.getLogger(__name__)


ADMIN_INTEGRATOR = "di-admin"
PRODUCER_INTEGRATOR = "di-producer"

LXD_CONTROLLER = get_controller_name("localhost")
MICROK8S_CONTROLLER = get_controller_name("microk8s")
assert MICROK8S_CONTROLLER, "No k8s controller detected!"

OAUTH_OFFER = f"{MICROK8S_CONTROLLER}:admin/{IAM_MODEL}.oauth-offer"
TLS_OFFER = f"{MICROK8S_CONTROLLER}:admin/{CORE_MODEL}.certificates"


def _cli_create_topic(conf_path: str, endpoints: str, topic: str):
    """Generate command to create a topic using the charmed-kafka.topics CLI client."""
    return f"sudo charmed-kafka.topics --bootstrap-server {endpoints} --command-config {conf_path}/client.properties --create --topic {topic}"


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
@use_controller(LXD_CONTROLLER)
def test_deploy_kafka(juju: jubilant.Juju, kafka_charm, kraft_mode, kafka_apps) -> None:
    """Deploys a cluster of Kafka with 3 brokers, waits for `active|idle`."""
    deploy_cluster(
        juju=juju,
        charm=kafka_charm,
        kraft_mode=kraft_mode,
        num_broker=3,
        num_controller=1,
    )

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=3,
        successes=20,
        timeout=900,
    )


@pytest.mark.abort_on_fail
@use_controller(MICROK8S_CONTROLLER)
def test_deploy_identity_platform():

    deploy_identity_platform()

    _juju = jubilant.Juju(model=IAM_MODEL)
    _juju.wait(
        lambda status: jubilant.all_agents_idle(status, *IAM_APPS)
        and jubilant.all_active(status, *IAM_APPS),
        delay=3,
        successes=20,
        timeout=900,
    )


@pytest.mark.abort_on_fail
@use_controller(LXD_CONTROLLER)
def test_integrate_oauth(juju: jubilant.Juju, kafka_apps):
    # Assert OAuth listener is not set yet.
    address = get_unit_ipv4_address(juju.model, f"{APP_NAME}/0")
    assert not check_socket(address, SECURITY_PROTOCOL_PORTS["SASL_SSL", "OAUTHBEARER"].client)

    # Consume the offers
    juju.cli("consume", TLS_OFFER)
    juju.cli("consume", OAUTH_OFFER)

    # Integrate with the consumed offers
    juju.integrate(f"{APP_NAME}:{TLS_RELATION}", TLS_OFFER)
    juju.integrate(APP_NAME, OAUTH_OFFER)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=3,
        successes=20,
        timeout=1200,
    )

    # Assert OAuth listener is set.
    assert check_socket(address, SECURITY_PROTOCOL_PORTS["SASL_SSL", "OAUTHBEARER"].client)


@pytest.mark.abort_on_fail
@use_controller(LXD_CONTROLLER)
def test_deploy_and_integrate_data_integrator(juju: jubilant.Juju, kafka_apps):
    juju.deploy(
        "data-integrator",
        app=ADMIN_INTEGRATOR,
        config={"topic-name": "__test-admin", "extra-user-roles": "admin"},
    )
    juju.deploy(
        "data-integrator",
        app=PRODUCER_INTEGRATOR,
        config={"topic-name": "test-topic", "extra-user-roles": "producer"},
    )
    juju.integrate(ADMIN_INTEGRATOR, APP_NAME)
    juju.integrate(PRODUCER_INTEGRATOR, APP_NAME)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, ADMIN_INTEGRATOR, PRODUCER_INTEGRATOR),
        delay=3,
        successes=20,
        timeout=1200,
    )


@pytest.mark.abort_on_fail
@use_controller(LXD_CONTROLLER)
def test_admin_client(juju: jubilant.Juju, kafka_apps):
    unit = f"{ADMIN_INTEGRATOR}/0"
    res = juju.run(unit, "get-credentials")

    username = res.results[APP_NAME]["username"]
    tls_ca = res.results[APP_NAME]["tls-ca"]
    kafka_endpoints = res.results[APP_NAME]["endpoints"]
    kafka_oauth_endpoints = kafka_endpoints.replace(
        f'{SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client}',
        f'{SECURITY_PROTOCOL_PORTS["SASL_SSL", "OAUTHBEARER"].client}',
    )

    with use_controller(MICROK8S_CONTROLLER):
        admin_client = create_oauth_client()

    client_conf_path = prepare_cli_client(
        juju,
        host_unit=unit,
        name="admin",
        oauth_client=admin_client,
        broker_ca=tls_ca,
    )

    # The user should be able to connect, but authorization should fail.
    with pytest.raises(jubilant.CLIError) as exc_info:
        juju.cli(
            "ssh",
            unit,
            _cli_create_topic(
                conf_path=client_conf_path, endpoints=kafka_oauth_endpoints, topic="test-1"
            ),
        )
        assert "Authorization failed" in exc_info.value.stdout

    # Define the roles-mapping
    juju.config(
        APP_NAME, values={"roles-mapping": f'{{"{admin_client.client_id}": "{username}"}}'}
    )

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=3,
        successes=20,
        timeout=1200,
    )

    # Now the command should succeed.
    juju.cli(
        "ssh",
        unit,
        _cli_create_topic(
            conf_path=client_conf_path, endpoints=kafka_oauth_endpoints, topic="test-1"
        ),
    )

    # Reset roles-mapping
    juju.config(APP_NAME, values={"roles-mapping": "{}"})

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=3,
        successes=20,
        timeout=1200,
    )

    # Topic creation should fail again.
    with pytest.raises(jubilant.CLIError) as exc_info:
        juju.cli(
            "ssh",
            unit,
            _cli_create_topic(
                conf_path=client_conf_path, endpoints=kafka_oauth_endpoints, topic="test-2"
            ),
        )
        assert "Authorization failed" in exc_info.value.stdout


@pytest.mark.abort_on_fail
@use_controller(LXD_CONTROLLER)
def test_producer_client(juju: jubilant.Juju, kafka_apps, tmp_path_factory):
    unit = f"{PRODUCER_INTEGRATOR}/0"
    res = juju.run(unit, "get-credentials")

    username = res.results[APP_NAME]["username"]
    tls_ca = res.results[APP_NAME]["tls-ca"]
    kafka_endpoints = res.results[APP_NAME]["endpoints"]
    kafka_internal_endpoints = kafka_endpoints.replace(
        f'{SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client}',
        f'{SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].internal}',
    )
    kafka_oauth_endpoints = kafka_endpoints.replace(
        f'{SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client}',
        f'{SECURITY_PROTOCOL_PORTS["SASL_SSL", "OAUTHBEARER"].client}',
    )

    with use_controller(MICROK8S_CONTROLLER):
        client = create_oauth_client()

    client_conf_path = prepare_cli_client(
        juju,
        host_unit=unit,
        name="producer",
        oauth_client=client,
        broker_ca=tls_ca,
    )

    # Define the roles-mapping
    juju.config(APP_NAME, values={"roles-mapping": f'{{"{client.client_id}": "{username}"}}'})

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=3,
        successes=20,
        timeout=1200,
    )

    # Topic creation should fail regardless, since this is a producer.
    with pytest.raises(jubilant.CLIError) as exc_info:
        juju.cli(
            "ssh",
            unit,
            _cli_create_topic(
                conf_path=client_conf_path, endpoints=kafka_oauth_endpoints, topic="any-topic"
            ),
        )
        assert "Authorization failed" in exc_info.value.stdout

    # Initialize KafkaProducer
    tmp_dir = tmp_path_factory.mktemp("producer")
    open(f"{tmp_dir}/ca.pem", "w").write(tls_ca)
    producer = kafka.KafkaProducer(
        bootstrap_servers=kafka_oauth_endpoints.split(","),
        ssl_cafile=f"{tmp_dir}/ca.pem",
        sasl_mechanism="OAUTHBEARER",
        security_protocol="SASL_SSL",
        sasl_oauth_token_provider=SimpleTokenProvider(
            client_id=client.client_id,
            client_secret=client.client_secret,
            token_endpoint=client.token_endpoint_uri,
        ),
    )

    # Produce to unauthorized topic
    future = producer.send("test-1", b"msg1")

    with pytest.raises(TopicAuthorizationFailedError):
        future.get(timeout=10)

    # Create the topic (test-topic) which the producer is authorized to publish
    juju.cli(
        "ssh",
        f"{APP_NAME}/0",
        _cli_create_topic(
            conf_path="/var/snap/charmed-kafka/current/etc/kafka/",
            endpoints=kafka_internal_endpoints,
            topic="test-topic",
        ),
    )

    # Test produce is succeeded
    future = producer.send("test-topic", b"msg1")
    future.get()
    assert future.succeeded()

    # Reset roles-mapping
    juju.config(APP_NAME, values={"roles-mapping": "{}"})

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=3,
        successes=20,
        timeout=1200,
    )

    # Try to produce to the previously authorized topic, should fail now
    future = producer.send("test-topic", b"msg2")

    with pytest.raises(TopicAuthorizationFailedError):
        future.get(timeout=10)


@pytest.mark.abort_on_fail
@use_controller(LXD_CONTROLLER)
def test_remove_oauth_relation(juju: jubilant.Juju, kafka_apps):
    juju.remove_relation(APP_NAME, "oauth-offer")

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=3,
        successes=20,
        timeout=1200,
        error=jubilant.any_error,
    )

    # Assert OAuth listener is not set.
    address = get_unit_ipv4_address(juju.model, f"{APP_NAME}/0")
    assert not check_socket(address, SECURITY_PROTOCOL_PORTS["SASL_SSL", "OAUTHBEARER"].client)
