import logging
from itertools import product
from time import sleep

from jubilant_adapters import JujuFixture, gather
from single_kernel_kafka.core.connect_models import PeerWorkersContext

from integration.connect_machine.helpers import (
    APP_NAME,
    KAFKA_APP,
    PLUGIN_RESOURCE_KEY,
    deploy_kafka,
    make_connect_api_request,
)

logger = logging.getLogger(__name__)

AUTH_SECRET_CONFIG_KEY = "system-users"
TEST_SECRET_NAME = "test-secret"
INTERNAL_USER = PeerWorkersContext.ADMIN_USERNAME
CUSTOM_AUTH = {INTERNAL_USER: "adminpass", "user1": "user1pass", "user2": "user2pass"}


def test_build_and_deploy(juju: JujuFixture, kafka_version: int, kafka_connect_charm):
    """Deploys kafka-connect charm along kafka (in KRaft mode)."""
    gather(
        juju.ext.model.deploy(
            kafka_connect_charm,
            application_name=APP_NAME,
            resources={
                PLUGIN_RESOURCE_KEY: "./tests/integration/connect_machine/resources/FakeResource.tar"
            },
            num_units=1,
            series="noble",
            config={"profile": "testing"},
        ),
        deploy_kafka(juju, kafka_version),
    )

    juju.ext.model.add_relation(APP_NAME, KAFKA_APP)
    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, KAFKA_APP], idle_period=30, timeout=1800, status="active"
        )


def test_add_auth_secret(juju: JujuFixture):
    """Checks the flow for defining custom username/passwords on Kafka Connect REST interface through user-defined secrets."""
    # add secret
    secret_id = juju.ext.model.add_secret(
        name=TEST_SECRET_NAME, data_args=[f"{u}={p}" for u, p in CUSTOM_AUTH.items()]
    )
    # grant access to our app
    juju.ext.model.grant_secret(secret_name=TEST_SECRET_NAME, application=APP_NAME)
    # configure the app to use the secret_id
    juju.ext.model.applications[APP_NAME].set_config({AUTH_SECRET_CONFIG_KEY: secret_id})

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(apps=[APP_NAME], idle_period=30, timeout=600)
        sleep(60)

    for username, password in CUSTOM_AUTH.items():
        response = make_connect_api_request(juju, custom_auth=(username, password))
        assert response.status_code == 200 if username == INTERNAL_USER else 401


def test_after_scale_out(juju: JujuFixture):
    """Checks custom username/passwords would be available on all units after scaling."""
    juju.ext.model.applications[APP_NAME].add_units(count=2)
    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME],
            idle_period=30,
            timeout=1200,
            status="active",
            wait_for_exact_units=3,
            raise_on_error=False,
        )

    # now let's test all credentials on all units
    for unit, creds in product(juju.ext.model.applications[APP_NAME].units, CUSTOM_AUTH.items()):
        username, password = creds
        response = make_connect_api_request(juju, unit=unit, custom_auth=(username, password))
        logger.info(f"Testing {username} on {unit.name}: {response.status_code}")
        assert response.status_code == 200 if username == INTERNAL_USER else 401


def test_update_secret(juju: JujuFixture):
    """Checks `update-secret` functionality."""
    # let's update admin password, remove user1 & user2 and add user3
    new_credentials = {"admin": "newadminpass", "user3": "user3pass"}

    juju.ext.model.update_secret(
        name=TEST_SECRET_NAME, data_args=[f"{u}={p}" for u, p in new_credentials.items()]
    )
    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME], idle_period=30, timeout=1200, status="active"
        )

    # now let's test old credentials on all units, they shouldn't work.
    for unit, creds in product(juju.ext.model.applications[APP_NAME].units, CUSTOM_AUTH.items()):
        username, password = creds
        response = make_connect_api_request(juju, unit=unit, custom_auth=(username, password))
        logger.info(f"Testing {username} on {unit.name}: {response.status_code}")
        assert response.status_code == 401

    # and new credentials should work!
    for unit, creds in product(
        juju.ext.model.applications[APP_NAME].units, new_credentials.items()
    ):
        username, password = creds
        response = make_connect_api_request(juju, unit=unit, custom_auth=(username, password))
        logger.info(f"Testing {username} on {unit.name}: {response.status_code}")
        assert response.status_code == 200 if username == INTERNAL_USER else 401


def test_remove_admin_user_is_safe(juju: JujuFixture):
    """Checks removing admin user from the user-defined secret wouldn't affect cluster functionality."""
    secret_id = juju.ext.model.add_secret(name="new-secret", data_args=["user4=user4pass"])
    juju.ext.model.grant_secret(secret_name="new-secret", application=APP_NAME)

    juju.ext.model.applications[APP_NAME].set_config({AUTH_SECRET_CONFIG_KEY: secret_id})

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME], idle_period=30, timeout=1200, status="active"
        )

    for unit in juju.ext.model.applications[APP_NAME].units:
        # If we don't provide `custom_auth` argument, `make_connect_api_request` will read
        # admin credentials from passwords file on the unit.
        response = make_connect_api_request(juju, unit=unit)
        assert response.status_code == 200
