import logging
import tempfile
from time import sleep

import pytest
from jubilant_adapters import JujuFixture, gather

from integration.connect_machine.helpers import (
    APP_NAME,
    JDBC_CONNECTOR_DOWNLOAD_LINK,
    KAFKA_APP,
    MYSQL_APP,
    MYSQL_CHANNEL,
    PLUGIN_RESOURCE_KEY,
    POSTGRES_APP,
    POSTGRES_CHANNEL,
    DatabaseFixtureParams,
    assert_connector_statuses,
    deploy_kafka,
    download_file,
    get_unit_ipv4_address,
    run_command_on_unit,
)

MYSQL_INTEGRATOR = "mysql-source-integrator"
MYSQL_DB = "test_db"
POSTGRES_INTEGRATOR = "postgres-sink-integrator"
POSTGRES_DB = "sink_db"


logger = logging.getLogger(__name__)


def test_build_and_deploy(juju: JujuFixture, kafka_version: int, kafka_connect_charm):
    """Deploys a basic test setup with Kafka, Kafka Connect, MySQL, and PostgreSQL."""
    gather(
        juju.ext.model.deploy(
            kafka_connect_charm,
            application_name=APP_NAME,
            series="noble",
            config={"profile": "testing"},
        ),
        deploy_kafka(juju, kafka_version),
        juju.ext.model.deploy(
            MYSQL_APP,
            channel=MYSQL_CHANNEL,
            application_name=MYSQL_APP,
            num_units=1,
            series="jammy",
        ),
        juju.ext.model.deploy(
            POSTGRES_APP,
            channel=POSTGRES_CHANNEL,
            application_name=POSTGRES_APP,
            num_units=1,
            series="jammy",
        ),
    )

    juju.ext.model.add_relation(APP_NAME, KAFKA_APP)
    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, KAFKA_APP, MYSQL_APP, POSTGRES_APP],
            idle_period=30,
            timeout=1800,
            status="active",
        )


def test_deploy_source_integrator(juju: JujuFixture, source_integrator_charm):
    """Deploys MySQL source integrator."""
    with tempfile.TemporaryDirectory() as temp_dir:
        plugin_path = f"{temp_dir}/jdbc-plugin.tar"
        logging.info(f"Downloading JDBC connectors from {JDBC_CONNECTOR_DOWNLOAD_LINK}...")
        download_file(JDBC_CONNECTOR_DOWNLOAD_LINK, plugin_path)
        logging.info("Download finished successfully.")

        juju.ext.model.deploy(
            source_integrator_charm,
            application_name=MYSQL_INTEGRATOR,
            resources={PLUGIN_RESOURCE_KEY: plugin_path},
            config={"mode": "source"},
        )

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[MYSQL_INTEGRATOR], idle_period=30, timeout=1800, status="blocked"
        )


def test_activate_source_integrator(juju: JujuFixture):
    """Checks source integrator becomes active after related with MySQL."""
    # our source mysql integrator need a mysql_client relation to unblock:
    juju.ext.model.add_relation(f"{MYSQL_INTEGRATOR}:data", MYSQL_APP)
    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[MYSQL_INTEGRATOR, MYSQL_APP], idle_period=30, timeout=600
        )

    assert juju.ext.model.applications[MYSQL_INTEGRATOR].status == "active"
    assert "UNKNOWN" in juju.ext.model.applications[MYSQL_INTEGRATOR].status_message


@pytest.mark.parametrize(
    "mysql_test_data",
    [DatabaseFixtureParams(app_name="mysql", db_name=MYSQL_DB, no_tables=1, no_records=20)],
    indirect=True,
)
def test_relate_with_connect_starts_source_integrator(juju: JujuFixture, mysql_test_data):
    """Checks source integrator task starts after relation with Kafka Connect."""
    # Hopefully, mysql_test_data fixture has filled our db with some test data.
    # Now it's time relate to Kafka Connect to start the task.
    logger.info("Loaded 20 records into source MySQL DB.")
    juju.ext.model.add_relation(MYSQL_INTEGRATOR, APP_NAME)

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[MYSQL_INTEGRATOR, APP_NAME], idle_period=30, timeout=600
        )

    assert juju.ext.model.applications[MYSQL_INTEGRATOR].status == "active"

    logging.info("Sleeping for a minute...")
    with juju.ext.fast_forward(fast_interval="20s"):
        sleep(60)

    # test task is running
    assert "RUNNING" in juju.ext.model.applications[MYSQL_INTEGRATOR].status_message


def test_deploy_postgres_sink_integrator(juju: JujuFixture, sink_integrator_charm):
    """Deploys PostgreSQL sink integrator."""
    with tempfile.TemporaryDirectory() as temp_dir:
        plugin_path = f"{temp_dir}/jdbc-plugin.tar"
        logging.info(f"Downloading JDBC connectors from {JDBC_CONNECTOR_DOWNLOAD_LINK}...")
        download_file(JDBC_CONNECTOR_DOWNLOAD_LINK, plugin_path)
        logging.info("Download finished successfully.")

        juju.ext.model.deploy(
            sink_integrator_charm,
            application_name=POSTGRES_INTEGRATOR,
            resources={PLUGIN_RESOURCE_KEY: plugin_path},
            config={"mode": "sink", "topics_regex": "test_.+"},
        )

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[POSTGRES_INTEGRATOR], idle_period=30, timeout=1800, status="blocked"
        )


def test_activate_sink_integrator(juju: JujuFixture):
    """Checks sink integrator becomes active after related with PostgreSQL."""
    # our sink postgres integrator need a postgresql relation to unblock:
    juju.ext.model.add_relation(f"{POSTGRES_INTEGRATOR}:data", POSTGRES_APP)
    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[MYSQL_INTEGRATOR, MYSQL_APP], idle_period=30, timeout=600
        )

    assert juju.ext.model.applications[POSTGRES_INTEGRATOR].status == "active"
    assert "UNKNOWN" in juju.ext.model.applications[POSTGRES_INTEGRATOR].status_message


def test_relate_with_connect_starts_sink_integrator(juju: JujuFixture):
    """Checks sink task starts after related with Kafka Connect and ensures records are being loaded into PostgreSQL sink db."""
    juju.ext.model.add_relation(POSTGRES_INTEGRATOR, APP_NAME)

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[POSTGRES_INTEGRATOR, APP_NAME], idle_period=30, timeout=600
        )

    assert juju.ext.model.applications[POSTGRES_INTEGRATOR].status == "active"

    logging.info("Sleeping for a minute...")
    with juju.ext.fast_forward(fast_interval="20s"):
        sleep(60)

    assert "RUNNING" in juju.ext.model.applications[POSTGRES_INTEGRATOR].status_message

    # Besides just checking the task status, we assert the end-to-end functionality
    # End-to-end test: we should have 20 records loaded into postgres:
    postgres_leader = juju.ext.model.applications[POSTGRES_APP].units[0]
    postgres_host = get_unit_ipv4_address(juju, postgres_leader)

    get_pass_action = postgres_leader.run_action("get-password", mode="full", dryrun=False)
    response = get_pass_action.wait()
    root_pass = response.results.get("password")

    res = run_command_on_unit(
        juju,
        postgres_leader,
        f"psql postgresql://operator:{root_pass}@{postgres_host}:5432/{POSTGRES_DB} -c 'SELECT COUNT(*) FROM \"test_table_1\"'",
    )

    logger.info("Checking number of records in sink Postgres DB (should be 20):")
    print(res.stdout)
    assert "20" in res.stdout


def test_relation_broken(juju: JujuFixture):
    """Checks `relation-broken` stops the connectors."""
    assert_connector_statuses(juju, running=2)

    juju.juju("remove-relation", APP_NAME, POSTGRES_INTEGRATOR)
    with juju.ext.fast_forward(fast_interval="30s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, POSTGRES_INTEGRATOR], idle_period=60, timeout=600
        )

    assert_connector_statuses(juju, running=1)

    # relate again with connect
    juju.ext.model.add_relation(APP_NAME, POSTGRES_INTEGRATOR)
    with juju.ext.fast_forward(fast_interval="30s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, POSTGRES_INTEGRATOR], idle_period=30, timeout=600
        )
        sleep(120)

    # new connector should show up in RUNNING state,
    # while previous connector should be in STOPPED state.
    assert_connector_statuses(juju, running=2)
