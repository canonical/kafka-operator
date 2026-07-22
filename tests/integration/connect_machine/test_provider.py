import logging
import tempfile

import pytest
from jubilant_adapters import JujuFixture, gather

from integration.connect_machine.helpers import (
    APP_NAME,
    JDBC_CONNECTOR_DOWNLOAD_LINK,
    JDBC_SOURCE_CONNECTOR_CLASS,
    KAFKA_APP,
    PLUGIN_RESOURCE_KEY,
    deploy_kafka,
    download_file,
    make_api_request,
    make_connect_api_request,
    search_secrets,
)

logger = logging.getLogger(__name__)

INTEGRATOR_APP = "test-integrator"
INTEGRATOR_PORT = 8080
USERNAME_CACHE_KEY = "integrator-username"
PASSWORD_CACHE_KEY = "integrator-password"


def test_deploy_app_and_integrator(
    juju: JujuFixture, kafka_version: int, kafka_connect_charm, source_integrator_charm
):

    # download JDBC connector plugin and deploy the integrator charm with it.
    with tempfile.TemporaryDirectory() as temp_dir:
        plugin_path = f"{temp_dir}/jdbc-plugin.tar"
        logging.info(f"Downloading JDBC connectors from {JDBC_CONNECTOR_DOWNLOAD_LINK}...")
        download_file(JDBC_CONNECTOR_DOWNLOAD_LINK, plugin_path)
        logging.info("Download finished successfully.")

        juju.ext.model.deploy(
            source_integrator_charm,
            application_name=INTEGRATOR_APP,
            resources={PLUGIN_RESOURCE_KEY: plugin_path},
            config={"mode": "source"},
        )

    # deploy kafka & kafka connect
    gather(
        juju.ext.model.deploy(
            kafka_connect_charm,
            application_name=APP_NAME,
            series="noble",
            config={"profile": "testing"},
        ),
        deploy_kafka(juju, kafka_version),
    )

    juju.ext.model.add_relation(APP_NAME, KAFKA_APP)

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, KAFKA_APP, INTEGRATOR_APP], idle_period=60, timeout=1800
        )

    assert juju.ext.model.applications[APP_NAME].status == "active"
    # dummy integrator boots up with blocked status, because BaseIntegrator.ready returns False.
    assert juju.ext.model.applications[INTEGRATOR_APP].status == "blocked"


def test_rest_endpoints_before_integration(juju: JujuFixture):
    # assert connect is up
    response = make_connect_api_request(juju)

    assert response.status_code == 200

    # assert connect doesn't have JDBC plugins loaded
    response = make_connect_api_request(juju, method="GET", endpoint="connector-plugins")
    assert response.status_code == 200

    connector_classes = [c.get("class") for c in response.json()]

    assert JDBC_SOURCE_CONNECTOR_CLASS not in connector_classes


def test_integrate(juju: JujuFixture, request: pytest.FixtureRequest):
    """Tests the integration functionality between Kafka Connect and integrator charm."""
    juju.ext.model.add_relation(APP_NAME, INTEGRATOR_APP)

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(apps=[APP_NAME, INTEGRATOR_APP], idle_period=30, timeout=600)

    # assert connect have JDBC plugins loaded after integration
    response = make_connect_api_request(juju, method="GET", endpoint="connector-plugins")
    connector_classes = [c.get("class") for c in response.json()]
    assert JDBC_SOURCE_CONNECTOR_CLASS in connector_classes

    username = search_secrets(juju, owner=APP_NAME, search_key="username")
    password = search_secrets(juju, owner=APP_NAME, search_key="password")

    # cache the values for next tests
    request.config.cache.set(USERNAME_CACHE_KEY, username)
    request.config.cache.set(PASSWORD_CACHE_KEY, password)

    assert username.startswith("relation-")

    # make sure the credentials work.
    response = make_api_request(juju, custom_auth=(username, password))
    assert response.status_code == 200

    # and the REST API is indeed protected.
    response = make_api_request(juju, custom_auth=(username, "wrong-password"))
    assert response.status_code == 401


def test_remove_integration(juju: JujuFixture, request: pytest.FixtureRequest):
    """Tests a broken integration leads to plugins being removed and credentials being revoked."""
    username = request.config.cache.get(USERNAME_CACHE_KEY, "")
    password = request.config.cache.get(PASSWORD_CACHE_KEY, "")

    juju.juju("remove-relation", APP_NAME, INTEGRATOR_APP)

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(apps=[APP_NAME, INTEGRATOR_APP], idle_period=30, timeout=600)

    # assert connect has removed JDBC plugins after integration is removed
    response = make_connect_api_request(juju, method="GET", endpoint="connector-plugins")
    connector_classes = [c.get("class") for c in response.json()]
    assert JDBC_SOURCE_CONNECTOR_CLASS not in connector_classes

    assert username.startswith("relation-")

    # make sure the credentials don't work anymore.
    response = make_api_request(juju, custom_auth=(username, password))
    assert response.status_code == 401
