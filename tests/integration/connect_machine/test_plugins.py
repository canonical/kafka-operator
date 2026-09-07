import logging
from time import sleep

from jubilant import Juju
from jubilant_adapters import JujuFixture, gather

from integration.connect_machine.helpers import (
    APP_NAME,
    JDBC_CONNECTOR_DOWNLOAD_LINK,
    JDBC_SINK_CONNECTOR_CLASS,
    JDBC_SOURCE_CONNECTOR_CLASS,
    KAFKA_APP,
    MYSQL_APP,
    MYSQL_CHANNEL,
    PLUGIN_RESOURCE_KEY,
    S3_CONNECTOR_CLASS,
    S3_CONNECTOR_LINK,
    build_mysql_db_init_queries,
    deploy_kafka,
    download_file,
    get_unit_ipv4_address,
    make_connect_api_request,
)

logger = logging.getLogger(__name__)

TEST_DB_USER = "testuser"
TEST_DB_PASS = "testpass"
TEST_DB_NAME = "testdb"
TEST_TASK_NAME = "test_task"


def test_build_and_deploy(juju: JujuFixture, kafka_version: int, kafka_connect_charm):
    """Deploys kafka-connect charm along kafka (in KRaft mode) & MySQL."""
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
        juju.ext.model.deploy(
            MYSQL_APP,
            channel=MYSQL_CHANNEL,
            application_name=MYSQL_APP,
            num_units=1,
            series="jammy",
        ),
    )

    juju.ext.model.add_relation(APP_NAME, KAFKA_APP)
    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, KAFKA_APP, MYSQL_APP], idle_period=30, timeout=1800, status="active"
        )


def test_add_plugin(juju: JujuFixture):
    """Checks attach-resource functionality using Aiven JDBC connector and ensures JDBC source/sink connector plugins are added."""
    plugin_path = f"{Juju()._temp_dir}/jdbc-plugin.tar"
    logging.info(f"Downloading JDBC connectors from {JDBC_CONNECTOR_DOWNLOAD_LINK}...")
    download_file(JDBC_CONNECTOR_DOWNLOAD_LINK, plugin_path)
    logging.info("Download finished successfully.")
    # attach resource
    juju.cli("attach-resource", APP_NAME, f"{PLUGIN_RESOURCE_KEY}={plugin_path}")

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(apps=[APP_NAME], idle_period=30, timeout=600)

    response = make_connect_api_request(juju, method="GET", endpoint="connector-plugins")
    assert response.status_code == 200

    connector_classes = [c.get("class") for c in response.json()]

    assert JDBC_SOURCE_CONNECTOR_CLASS in connector_classes
    assert JDBC_SINK_CONNECTOR_CLASS in connector_classes


def test_mysql_setup(juju: JujuFixture):
    """Bootstraps MySQL database with test data and ensures testbed integrity."""
    mysql_leader = juju.ext.model.applications[MYSQL_APP].units[0]
    get_pass_action = mysql_leader.run_action("get-password", mode="full", dryrun=False)
    response = get_pass_action.wait()

    mysql_root_pass = response.results.get("password")
    mysql_host = get_unit_ipv4_address(juju, mysql_leader)

    for query in build_mysql_db_init_queries(
        test_db_host=str(mysql_host),
        test_db_user=TEST_DB_USER,
        test_db_pass=TEST_DB_PASS,
        test_db_name=TEST_DB_NAME,
    ):
        cmd = f'mysql -h 127.0.0.1 -u root -p{mysql_root_pass} -e "{query}"'
        print(cmd.replace(mysql_root_pass, "******").replace(TEST_DB_PASS, "******"))
        return_code, _, _ = juju.juju("ssh", f"{mysql_leader.name}", cmd)
        assert return_code == 0


def test_add_task(juju: JujuFixture):
    """Checks whether connector plugin is usable or not by adding a sample test task using MySQL source."""
    mysql_leader = juju.ext.model.applications[MYSQL_APP].units[0]
    mysql_host = get_unit_ipv4_address(juju, mysql_leader)

    task_json = {
        "name": TEST_TASK_NAME,
        "config": {
            "mode": "bulk",
            "connector.class": JDBC_SOURCE_CONNECTOR_CLASS,
            "topics": "test",
            "connection.url": f"jdbc:mysql://{mysql_host}:3306/{TEST_DB_NAME}",
            "connection.user": TEST_DB_USER,
            "connection.password": TEST_DB_PASS,
            "topic.prefix": "test_etl_",
            "tasks.max": "1",
            "auto.create": True,
            "auto.evolve": True,
            "insert.mode": "upsert",
            "pk.mode": "record_key",
            "pk.fields": "id",
            "value.converter": "org.apache.kafka.connect.json.JsonConverter",
        },
    }

    response = make_connect_api_request(juju, method="POST", endpoint="connectors", json=task_json)

    assert response.status_code == 201


def test_task_is_running(juju: JujuFixture):
    """Checks whether the added task is in RUNNING state."""
    # wait for 60s
    sleep(60)

    tasks_response = make_connect_api_request(
        juju, method="GET", endpoint=f"connectors/{TEST_TASK_NAME}/tasks", timeout=10
    )

    assert tasks_response.status_code == 200
    tasks = tasks_response.json()
    assert len(tasks) == 1  # 1 task should be submitted here

    task_id = tasks[0].get("id", {}).get("task", 0)
    status_response = make_connect_api_request(
        juju,
        method="GET",
        endpoint=f"connectors/{TEST_TASK_NAME}/tasks/{task_id}/status",
        timeout=10,
    )

    assert status_response.status_code == 200
    assert status_response.json().get("state") == "RUNNING"


def test_add_another_plugin(juju: JujuFixture):
    """Checks attaching new plugins work as expected, preserving the old ones."""
    plugin_path = f"{Juju()._temp_dir}/jdbc-plugin.tar"
    logging.info(f"Downloading S3 connectors from {S3_CONNECTOR_LINK}...")
    download_file(S3_CONNECTOR_LINK, plugin_path)
    logging.info("Download finished successfully.")
    # attach resource
    juju.cli("attach-resource", APP_NAME, f"{PLUGIN_RESOURCE_KEY}={plugin_path}")

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(apps=[APP_NAME], idle_period=30, timeout=600)

    response = make_connect_api_request(juju, method="GET", endpoint="connector-plugins")
    assert response.status_code == 200

    connector_classes = [c.get("class") for c in response.json()]

    assert S3_CONNECTOR_CLASS in connector_classes
    assert JDBC_SOURCE_CONNECTOR_CLASS in connector_classes
    assert JDBC_SINK_CONNECTOR_CLASS in connector_classes
