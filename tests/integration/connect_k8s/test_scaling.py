import logging
import tempfile
from time import sleep

import pytest
from jubilant_adapters import JujuFixture, gather

from integration.connect_k8s.helpers import (
    APP_NAME,
    IMAGE_RESOURCE_KEY,
    IMAGE_URI,
    JDBC_CONNECTOR_DOWNLOAD_LINK,
    KAFKA_APP,
    KAFKA_CHANNEL,
    MYSQL_APP,
    MYSQL_CHANNEL,
    PLUGIN_RESOURCE_KEY,
    DatabaseFixtureParams,
    destroy_active_workers,
    download_file,
    make_connect_api_request,
)

logger = logging.getLogger(__name__)


MYSQL_DB = "test_db"
INTEGRATOR = "integrator"


def test_build_and_deploy(juju: JujuFixture, kafka_connect_charm):
    """Deploys kafka-connect charm along kafka (in KRaft mode) & MySQL."""
    gather(
        juju.ext.model.deploy(
            kafka_connect_charm,
            application_name=APP_NAME,
            resources={
                IMAGE_RESOURCE_KEY: IMAGE_URI,
                PLUGIN_RESOURCE_KEY: "./tests/integration/connect_k8s/resources/FakeResource.tar",
            },
            num_units=1,
        ),
        juju.ext.model.deploy(
            KAFKA_APP,
            channel=KAFKA_CHANNEL,
            application_name=KAFKA_APP,
            num_units=1,
            config={"roles": "broker,controller"},
        ),
        juju.ext.model.deploy(
            MYSQL_APP,
            channel=MYSQL_CHANNEL,
            application_name=MYSQL_APP,
            num_units=1,
            trust=True,
        ),
    )

    juju.ext.model.add_relation(APP_NAME, KAFKA_APP)
    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, KAFKA_APP, MYSQL_APP], idle_period=30, timeout=1800, status="active"
        )


def test_deploy_integrator(juju: JujuFixture, integrator_charm):
    """Deploys MySQL source integrator."""
    with tempfile.TemporaryDirectory() as temp_dir:
        plugin_path = f"{temp_dir}/jdbc-plugin.tar"
        logging.info(f"Downloading JDBC connectors from {JDBC_CONNECTOR_DOWNLOAD_LINK}...")
        download_file(JDBC_CONNECTOR_DOWNLOAD_LINK, plugin_path)
        logging.info("Download finished successfully.")

        juju.ext.model.deploy(
            integrator_charm,
            application_name=INTEGRATOR,
            resources={PLUGIN_RESOURCE_KEY: plugin_path},
            config={"mode": "source"},
        )

    juju.ext.model.add_relation(INTEGRATOR, MYSQL_APP)
    juju.ext.model.add_relation(INTEGRATOR, APP_NAME)

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[INTEGRATOR], idle_period=30, timeout=1800, status="active"
        )


@pytest.mark.parametrize(
    "mysql_test_data",
    [DatabaseFixtureParams(app_name=MYSQL_APP, db_name=MYSQL_DB, no_tables=1, no_records=93)],
    indirect=True,
)
def test_load_data(juju: JujuFixture, mysql_test_data):
    """Loads test data into MySQL DB and ensures connector transitions into RUNNING state."""
    # Hopefully, mysql_test_data fixture has filled our db with some test data.
    # Now it's time relate to Kafka Connect to start the task.
    logger.info("Loaded 93 records into source MySQL DB.")

    with juju.ext.fast_forward(fast_interval="30s"):
        sleep(120)

    assert "RUNNING" in juju.ext.model.applications[INTEGRATOR].status_message


def test_scale_out(juju: JujuFixture):
    juju.ext.model.applications[APP_NAME].add_units(count=2)
    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME], idle_period=30, timeout=1200, status="active", wait_for_exact_units=3
        )

    with juju.ext.fast_forward(fast_interval="30s"):
        juju.ext.model.block_until(
            lambda: "RUNNING" in juju.ext.model.applications[INTEGRATOR].status_message,
            timeout=600,
            wait_period=15,
        )

    for unit in juju.ext.model.applications[APP_NAME].units:
        status_resp = make_connect_api_request(
            juju, unit=unit, endpoint="connectors?expand=status"
        )
        assert status_resp.status_code == 200
        status_json = status_resp.json()
        for connector in status_json:
            assert status_json[connector]["status"]["connector"]["state"] == "RUNNING"


def test_destroy_active_workers(juju: JujuFixture):
    """Checks scaling in functionality by destroying workers with active connectors.

    This test ensures that connector tasks are resumed on remaining worker(s).
    """
    # delete pods with active connectors for 5 times
    for _ in range(5):
        destroy_active_workers(juju)

        with juju.ext.fast_forward(fast_interval="60s"):
            juju.ext.model.wait_for_idle(
                apps=[INTEGRATOR, APP_NAME],
                idle_period=30,
                timeout=600,
                status="active",
                raise_on_error=False,
            )

    logging.info("Sleeping for two minutes...")
    with juju.ext.fast_forward(fast_interval="30s"):
        sleep(120)

    # assert the task is RUNNING after the mayhem!
    status_resp = make_connect_api_request(juju, endpoint="connectors?expand=status")
    assert {item["status"]["connector"]["state"] for item in status_resp.json().values()} == {
        "RUNNING"
    }

    # scale down to 1 unit
    juju.ext.model.applications[APP_NAME].scale(scale=1)
    juju.ext.model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        timeout=600,
        idle_period=20,
        wait_for_exact_units=1,
    )

    logging.info("Sleeping for two minutes...")
    with juju.ext.fast_forward(fast_interval="30s"):
        sleep(120)

    status_resp = make_connect_api_request(juju, endpoint="connectors?expand=status")
    assert {item["status"]["connector"]["state"] for item in status_resp.json().values()} == {
        "RUNNING"
    }

    # assert the task is running on the remaining pod
    remaining_unit = juju.ext.model.applications[APP_NAME].units[0]
    parts = remaining_unit.name.split("/")
    unit_name, unit_id = parts
    assert {
        item["status"]["connector"]["worker_id"].split(":")[0]
        for item in status_resp.json().values()
    } == {f"{unit_name}-{unit_id}.{APP_NAME}-endpoints"}
