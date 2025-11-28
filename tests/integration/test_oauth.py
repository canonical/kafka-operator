#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import os
import textwrap

import jubilant
import pytest

from integration.helpers import (
    APP_NAME,
    bootstrap_microk8s,
    deploy_identity_platform,
    get_controller_name,
)
from integration.helpers.jubilant import (
    all_active_idle,
    deploy_cluster,
    get_unit_ipv4_address,
)
from integration.helpers.pytest_operator import check_socket
from literals import SECURITY_PROTOCOL_PORTS, TLS_RELATION

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker


CORE_MODEL = "core"
IAM_MODEL = "iam"
IAM_APPS = ["hydra", "kratos"]
TRAEFIK_APP = "traefik-public"
INTEGRATOR_APP = "data-integrator"


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
def test_deploy_kafka(
    juju: jubilant.Juju, lxd_controller: str, kafka_charm, kraft_mode, kafka_apps
) -> None:
    """Deploys a cluster of Kafka with 3 brokers, waits for `active|idle`."""
    os.system(f"juju switch {lxd_controller}")
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
def test_deploy_identity_platform(microk8s_controller: str | None):
    if not microk8s_controller:
        bootstrap_microk8s()

    microk8s = get_controller_name("microk8s")
    os.system(f"juju switch {microk8s}")
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
def test_integrate_oauth(
    juju: jubilant.Juju, lxd_controller: str | None, microk8s_controller: str | None, kafka_apps
):
    os.system(f"juju switch {lxd_controller}")

    # Assert OAuth listener is not set yet.
    address = get_unit_ipv4_address(juju.model, f"{APP_NAME}/0")
    assert not check_socket(address, SECURITY_PROTOCOL_PORTS["SASL_SSL", "OAUTHBEARER"].client)

    # find TLS & OAuth offers
    offers = json.loads(
        juju.cli(
            "find-offers",
            "-m",
            f"{microk8s_controller}:{CORE_MODEL}",
            "--format",
            "json",
            include_model=False,
        )
    ).keys()

    tls_offer = None
    oauth_offer = None
    for offer in offers:
        if "certificates" in offer:
            tls_offer = offer
        elif "oauth-offer" in offer:
            oauth_offer = offer

    if not all([tls_offer, oauth_offer]):
        raise Exception("Can't find TLS/OAuth offers")

    # Consume the offers
    juju.cli("consume", tls_offer)
    juju.cli("consume", oauth_offer)

    # Integrate with the consumed offers
    juju.integrate(f"{APP_NAME}:{TLS_RELATION}", tls_offer)
    juju.integrate(APP_NAME, oauth_offer)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=3,
        successes=20,
        timeout=1200,
    )

    # Assert OAuth listener is set.
    assert check_socket(address, SECURITY_PROTOCOL_PORTS["SASL_SSL", "OAUTHBEARER"].client)


@pytest.mark.abort_on_fail
def test_deploy_and_integrate_data_integrator(juju: jubilant.Juju, kafka_apps):
    juju.deploy(
        INTEGRATOR_APP,
        app=INTEGRATOR_APP,
        config={"topic-name": "__test-admin", "extra-user-roles": "admin"},
    )
    juju.integrate(INTEGRATOR_APP, APP_NAME)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, INTEGRATOR_APP),
        delay=3,
        successes=20,
        timeout=1200,
    )


def test_an_oauth_client_on_data_integrator(
    juju: jubilant.Juju,
    lxd_controller: str | None,
    microk8s_controller: str | None,
    kafka_apps,
    tmp_path_factory,
):
    os.system(f"juju switch {lxd_controller}")
    res = juju.run(f"{INTEGRATOR_APP}/0", "get-credentials")
    tls_ca = res.results[APP_NAME]["tls-ca"]
    kafka_endpoints = res.results[APP_NAME]["endpoints"]
    kafka_oauth_endpoints = kafka_endpoints.replace(
        f'{SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client}',
        f'{SECURITY_PROTOCOL_PORTS["SASL_SSL", "OAUTHBEARER"].client}',
    )

    os.system(f"juju switch {microk8s_controller}")

    iam_juju = jubilant.Juju(model=IAM_MODEL)
    res = iam_juju.run(
        "hydra/0",
        "create-oauth-client",
        params={
            "scope": ["profile", "email", "phone", "offline"],
            "grant-types": ["client_credentials"],
            "audience": ["kafka"],
        },
    )
    client_id = res.results["client-id"]
    client_secret = res.results["client-secret"]

    core_juju = jubilant.Juju(model=CORE_MODEL)
    res = core_juju.run(f"{TRAEFIK_APP}/0", "show-proxied-endpoints")
    endpoints = json.loads(res.results["proxied-endpoints"])
    base_uri = endpoints[TRAEFIK_APP]["url"]
    token_endpoint_uri = f"{base_uri}/oauth2/token"

    truststore_password = "tspass"
    base_path = "/var/snap/charmed-kafka/current/etc/kafka"
    truststore_path = f"{base_path}/oauth-client.jks"

    client_properties = textwrap.dedent(
        f"""
        security.protocol=SASL_SSL
        sasl.mechanism=OAUTHBEARER
        sasl.jaas.config=org.apache.kafka.common.security.oauthbearer.OAuthBearerLoginModule required oauth.client.id="{client_id}" oauth.client.secret="{client_secret}" oauth.token.endpoint.uri="{token_endpoint_uri}" oauth.scope="profile" oauth.ssl.truststore.location="{truststore_path}" oauth.ssl.truststore.password="{truststore_password}" oauth.ssl.truststore.type="JKS" oauth.audience="kafka";
        sasl.login.callback.handler.class=io.strimzi.kafka.oauth.client.JaasClientOauthLoginCallbackHandler
        ssl.truststore.location={truststore_path}
        ssl.truststore.password={truststore_password}
    """
    )

    # Save the properties and the CA into temp files
    client_dir = tmp_path_factory.mktemp("client")
    with open(f"{client_dir}/client.properties", "w") as f:
        f.write(client_properties)

    with open(f"{client_dir}/server.pem", "w") as f:
        f.write(tls_ca)

    os.system(f"juju switch {lxd_controller}")

    # Install charmed-kafka on data-integrator
    juju.cli("ssh", f"{INTEGRATOR_APP}/0", "sudo snap install charmed-kafka --channel 4/edge")
    juju.cli("scp", f"{client_dir}/client.properties", f"{INTEGRATOR_APP}/0:/home/ubuntu/")
    juju.cli("scp", f"{client_dir}/server.pem", f"{INTEGRATOR_APP}/0:/home/ubuntu/")

    truststore_command = f"sudo charmed-kafka.keytool -import -alias ca -file {base_path}/server.pem -keystore {truststore_path} -storepass {truststore_password} -noprompt"
    juju.cli("ssh", f"{INTEGRATOR_APP}/0", f"sudo cp /home/ubuntu/server.pem {base_path}")
    juju.cli("ssh", f"{INTEGRATOR_APP}/0", f"sudo cp /home/ubuntu/client.properties {base_path}")
    juju.cli("ssh", f"{INTEGRATOR_APP}/0", truststore_command)
    juju.cli("ssh", f"{INTEGRATOR_APP}/0", f"sudo chmod a+x {truststore_path}")

    create_topic_command = f"sudo charmed-kafka.topics --bootstrap-server {kafka_oauth_endpoints} --command-config {base_path}/client.properties --create --topic test"

    # The user should be able to connect, but authorization should fail.
    with pytest.raises(jubilant.CLIError) as exc_info:
        juju.cli("ssh", f"{INTEGRATOR_APP}/0", create_topic_command)
        assert "Authorization failed" in exc_info.value.stdout
