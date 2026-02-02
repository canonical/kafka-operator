import dataclasses
import json
import os
import tempfile
import textwrap

import jubilant
import requests
from kafka.sasl.oauth import AbstractTokenProvider

from . import _run_script

CORE_MODEL = "core"
IAM_MODEL = "iam"
IAM_APPS = ["hydra", "kratos"]
TRAEFIK_APP = "traefik-public"


@dataclasses.dataclass
class OAuthClient:
    """Data class for test OAuth clients."""

    client_id: str
    client_secret: str
    token_endpoint_uri: str


class SimpleTokenProvider(AbstractTokenProvider):
    def __init__(self, client_id: str, client_secret: str, token_endpoint: str):
        self._token: str = ""
        self._expires: int | None = None
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_endpoint = token_endpoint
        self._refresh()

    def _refresh(self):
        resp = requests.post(
            self._token_endpoint,
            auth=(self._client_id, self._client_secret),
            verify=False,
            data={"scope": "profile", "grant_type": "client_credentials", "audience": "kafka"},
        )
        json_ = resp.json()
        self._token = json_["access_token"]
        self._expires = json_["expires_in"]

    def token(self):
        if not self._token:
            self._refresh()

        return self._token


def create_oauth_client() -> OAuthClient:
    """Create an OAuth client using the hydra app."""
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

    return OAuthClient(
        client_id=client_id, client_secret=client_secret, token_endpoint_uri=token_endpoint_uri
    )


def deploy_identity_platform(git_tag: str = "v1.0.0") -> None:
    """Deploy the Canonical Identity Platform Terraform bundle."""
    home = os.environ.get("HOME", "/tmp")
    _run_script(
        f"""
        mkdir {home}/iam-bundle
        git clone --branch {git_tag} https://github.com/canonical/iam-bundle-integration.git {home}/iam-bundle
        terraform -chdir={home}/iam-bundle/examples/tutorial init
        terraform -chdir={home}/iam-bundle/examples/tutorial apply -auto-approve
    """
    )


def prepare_cli_client(
    juju: jubilant.Juju,
    host_unit: str,
    name: str,
    oauth_client: OAuthClient,
    broker_ca: str,
    truststore_password: str = "trustP4ss",
) -> str:
    """Generate properties for Apache Kafka CLI client, for a given OAuthClient.

    Args:
        juju: jubilant.Juju fixture.
        host_unit: name of the unit which is going to host the client application.
        name: an arbitrary name given to the client to distinguish it from other clients.
        oauth_client: OAuthClient object containing client's credentials.
        broker_ca: CA certificate of the Apache Kafka broker.
        truststore_password: password of the truststore generated for the client.
    """
    tmp_dir = tempfile.mkdtemp(dir=juju._temp_dir)

    base_path = f"/var/snap/charmed-kafka/current/etc/kafka/client-{name}"
    truststore_path = f"{base_path}/truststore.jks"
    client_properties = textwrap.dedent(
        f"""
        security.protocol=SASL_SSL
        sasl.mechanism=OAUTHBEARER
        sasl.jaas.config=org.apache.kafka.common.security.oauthbearer.OAuthBearerLoginModule required oauth.client.id="{oauth_client.client_id}" oauth.client.secret="{oauth_client.client_secret}" oauth.token.endpoint.uri="{oauth_client.token_endpoint_uri}" oauth.scope="profile" oauth.ssl.truststore.location="{truststore_path}" oauth.ssl.truststore.password="{truststore_password}" oauth.ssl.truststore.type="JKS" oauth.audience="kafka";
        sasl.login.callback.handler.class=io.strimzi.kafka.oauth.client.JaasClientOauthLoginCallbackHandler
        ssl.truststore.location={truststore_path}
        ssl.truststore.password={truststore_password}
    """
    )

    # Save the properties and the CA into temp files
    with open(f"{tmp_dir}/client.properties", "w") as f:
        f.write(client_properties)

    with open(f"{tmp_dir}/broker-ca.pem", "w") as f:
        f.write(broker_ca)

    # Copy the files into the host unit
    juju.cli("ssh", host_unit, "sudo snap install charmed-kafka --channel 4/edge")
    juju.cli("scp", f"{tmp_dir}/client.properties", f"{host_unit}:/home/ubuntu/")
    juju.cli("scp", f"{tmp_dir}/broker-ca.pem", f"{host_unit}:/home/ubuntu/")

    juju.cli("ssh", host_unit, f"sudo mkdir -p {base_path}")
    juju.cli("ssh", host_unit, f"sudo cp /home/ubuntu/broker-ca.pem {base_path}")
    juju.cli("ssh", host_unit, f"sudo cp /home/ubuntu/client.properties {base_path}")

    truststore_command = f"sudo charmed-kafka.keytool -import -alias ca -file {base_path}/broker-ca.pem -keystore {truststore_path} -storepass {truststore_password} -noprompt"
    juju.cli("ssh", host_unit, truststore_command)
    juju.cli("ssh", host_unit, f"sudo chmod a+x {truststore_path}")

    return base_path
