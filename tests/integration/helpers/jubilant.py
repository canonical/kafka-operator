#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import re
import socket
from contextlib import closing
from pathlib import Path
from subprocess import PIPE, CalledProcessError, check_output
from typing import Any, Literal, Mapping

import jubilant
import yaml
from charms.kafka.v0.client import KafkaClient
from charms.tls_certificates_interface.v4.tls_certificates import PrivateKey
from kafka.admin import NewTopic
from tenacity import retry, retry_if_result
from tenacity.stop import stop_after_attempt
from tenacity.wait import wait_fixed

from core.models import JSON
from literals import (
    BALANCER_WEBSERVER_USER,
    JMX_CC_PORT,
    PATHS,
    PEER,
    PEER_CLUSTER_ORCHESTRATOR_RELATION,
    PEER_CLUSTER_RELATION,
)
from managers.auth import Acl, AuthManager
from managers.balancer import BalancerManager

from . import (
    APP_NAME,
    AUTH_SECRET_CONFIG_KEY,
    AUTH_SECRET_NAME,
    CONTROLLER_NAME,
    TEST_DEFAULT_MESSAGES,
    TLS_SECRET_CONFIG_KEY,
    TLS_SECRET_NAME,
    KRaftMode,
    KRaftUnitStatus,
)

logger = logging.getLogger(__name__)

BASE = "ubuntu@24.04"


def all_active_idle(status: jubilant.Status, *apps: str):
    """Helper function for jubilant all units active|idle checks."""
    return jubilant.all_agents_idle(status, *apps) and jubilant.all_active(status, *apps)


def deploy_cluster(
    juju: jubilant.Juju,
    charm: Path,
    kraft_mode: KRaftMode,
    series: str = "noble",
    config_broker: dict = {},
    config_controller: dict = {},
    num_broker: int = 1,
    num_controller: int = 1,
    storage_broker: dict = {},
    app_name_broker: str = str(APP_NAME),
    app_name_controller: str = CONTROLLER_NAME,
    bind: Mapping[str, str] = {},
    channel: str | None = None,
):
    """Deploys an Apache Kafka cluster using the Charmed Apache Kafka operator in KRaft mode."""
    logger.info(f"Deploying Kafka cluster in '{kraft_mode}' mode")

    base = "ubuntu@24.04" if series == "noble" else "ubuntu@22.04"

    juju.deploy(
        charm,
        app=app_name_broker,
        num_units=num_broker,
        base=base,
        storage=storage_broker,
        config={
            "roles": "broker,controller" if kraft_mode == "single" else "broker",
            "profile": "testing",
        }
        | config_broker,
        trust=True,
        bind=bind,
        channel=channel if channel else None,
    )

    if kraft_mode == "multi":
        juju.deploy(
            charm,
            app=app_name_controller,
            num_units=num_controller,
            base=base,
            config={
                "roles": "controller",
                "profile": "testing",
            }
            | config_controller,
            trust=True,
            bind=bind,
            channel=channel if channel else None,
        )

    assert_status_func = jubilant.all_active if kraft_mode == "single" else jubilant.all_blocked
    apps = [app_name_broker] if kraft_mode == "single" else [app_name_broker, app_name_controller]

    juju.wait(
        lambda status: jubilant.all_agents_idle(status, *apps)
        and assert_status_func(status, *apps),
        delay=3,
        successes=10,
        timeout=1800,
    )

    if kraft_mode == "multi":
        juju.integrate(
            f"{app_name_broker}:{PEER_CLUSTER_ORCHESTRATOR_RELATION}",
            f"{app_name_controller}:{PEER_CLUSTER_RELATION}",
        )

    juju.wait(
        lambda status: all_active_idle(status, *apps),
        delay=3,
        successes=10,
        timeout=1800,
    )


def get_unit_ipv4_address(model_full_name: str | None, unit_name: str) -> str | None:
    """A safer alternative for `juju.unit.get_public_address()` which is robust to network changes."""
    try:
        stdout = check_output(
            f"JUJU_MODEL={model_full_name} juju ssh {unit_name} hostname -i",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )
    except CalledProcessError:
        return None

    ipv4_matches = re.findall(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}", stdout)

    if ipv4_matches:
        return ipv4_matches[0]

    return None


def load_acls(model_full_name: str | None) -> set[Acl]:
    bootstrap_server = f"{get_unit_ipv4_address(model_full_name, 'kafka/0')}:19093"
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh kafka/0 sudo -i 'charmed-kafka.acls --command-config {PATHS['kafka']['CONF']}/client.properties --bootstrap-server {bootstrap_server} --list'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return AuthManager._parse_acls(acls=result)


def load_super_users(model_full_name: str | None) -> list[str]:
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh kafka/0 sudo -i 'cat /var/snap/charmed-kafka/current/etc/kafka/server.properties'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )
    properties = result.splitlines()

    for prop in properties:
        if "super.users" in prop:
            return prop.split("=")[1].split(";")

    return []


def check_user(model_full_name: str | None, username: str) -> None:
    bootstrap_server = f"{get_unit_ipv4_address(model_full_name, 'kafka/0')}:19093"
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh kafka/0 sudo -i 'charmed-kafka.configs --bootstrap-server {bootstrap_server} --describe --entity-type users --entity-name {username}' --command-config /var/snap/charmed-kafka/current/etc/kafka/client.properties",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    assert f"SCRAM credential configs for user-principal '{username}' are SCRAM-SHA-512" in result


def get_user(model_full_name: str | None, username: str = "sync") -> str:
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh kafka/0 sudo -i 'cat /var/snap/charmed-kafka/current/etc/kafka/server.properties'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    ).splitlines()

    for line in result:
        if f'required username="{username}"' in line:
            break

    return line


def set_password(juju: jubilant.Juju, username: str = "sync", password: str = "testpass") -> None:
    """Use the charm `system-users` config option to start a password rotation."""
    custom_auth = {username: password, "foo": "bar"}
    secret_id = juju.add_secret(name=AUTH_SECRET_NAME, content=custom_auth)

    # grant access to our app
    juju.grant_secret(AUTH_SECRET_NAME, app=APP_NAME)

    # configure the app to use the secret_id
    juju.config(APP_NAME, values={AUTH_SECRET_CONFIG_KEY: secret_id})


def set_tls_private_key(juju: jubilant.Juju, secret: dict[str, PrivateKey]) -> None:
    """Use the charm `tls-private-key` config option to set a PK."""
    custom_tls_data = {unit_name: f"{tls_pk}" for unit_name, tls_pk in secret.items()}
    secret_id = juju.add_secret(name=TLS_SECRET_NAME, content=custom_tls_data)

    # grant access to our app
    juju.grant_secret(TLS_SECRET_NAME, app=APP_NAME)

    # configure the app to use the secret_id
    juju.config(APP_NAME, values={TLS_SECRET_CONFIG_KEY: secret_id})


def update_tls_private_key(juju: jubilant.Juju, secret: dict[str, PrivateKey]) -> None:
    """Update the `tls-private-key` config option secret to change a PK."""
    updated_tls_data = {unit_name: f"{tls_pk}" for unit_name, tls_pk in secret.items()}
    juju.update_secret(TLS_SECRET_NAME, updated_tls_data)


def remove_tls_private_key(juju: jubilant.Juju) -> None:
    """Remove the `tls-private-key` config option secret."""
    juju.config(APP_NAME, values={TLS_SECRET_CONFIG_KEY: ""})


def get_actual_tls_private_key(juju: jubilant.Juju, unit_name: str) -> str:
    return check_output(
        f"JUJU_MODEL={juju.model} juju ssh {unit_name} sudo -i 'cat /var/snap/charmed-kafka/current/etc/kafka/client-server.key'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )


def extract_private_key(juju: jubilant.Juju, unit_name: str) -> str | None:
    user_secret = get_secret_by_label(
        juju,
        label=f"cluster.{unit_name.split('/')[0]}.unit",
        owner=unit_name,
    )

    return user_secret.get("client-private-key")


def extract_ca(juju: jubilant.Juju, unit_name: str) -> str | None:
    user_secret = get_secret_by_label(
        juju,
        label=f"cluster.{unit_name.split('/')[0]}.unit",
        owner=unit_name,
    )

    return user_secret.get("ca-cert") or user_secret.get("ca")


def extract_truststore_password(juju: jubilant.Juju, unit_name: str) -> str | None:
    user_secret = get_secret_by_label(
        juju,
        label=f"cluster.{unit_name.split('/')[0]}.unit",
        owner=unit_name,
    )

    return user_secret.get("truststore-password")


def check_socket(host: str, port: int) -> bool:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        return sock.connect_ex((host, port)) == 0


def check_tls(ip: str, port: int) -> bool:
    try:
        result = check_output(
            f"echo | openssl s_client -connect {ip}:{port}",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )
        return bool(result)

    except CalledProcessError as e:
        logger.error(f"command '{e.cmd}' return with error (code {e.returncode}): {e.output}")
        return False


def consume_and_check(juju: jubilant.Juju, provider_unit_name: str, topic: str) -> None:
    """Consumes 15 messages created by `produce_and_check_logs` function.

    Args:
        juju: jubilant.Juju
        provider_unit_name: the app to grab credentials from
        topic: the desired topic to consume from
    """
    relation_data = get_provider_data(
        model=juju.model,
        unit_name=provider_unit_name,
        owner=APP_NAME,
    )
    topic = topic
    username = relation_data.get("username", None)
    password = relation_data.get("password", None)
    servers = relation_data.get("endpoints", "").split(",")
    security_protocol = "SASL_PLAINTEXT"

    if not (username and password and servers):
        raise KeyError("missing relation data from app charm")

    client = KafkaClient(
        servers=servers,
        username=username,
        password=password,
        security_protocol=security_protocol,
    )

    client.subscribe_to_topic(topic_name=topic)
    messages = [*client.messages()]

    assert len(messages) == TEST_DEFAULT_MESSAGES


def produce_and_check_logs(
    juju: jubilant.Juju,
    kafka_unit_name: str,
    provider_unit_name: str,
    topic: str,
    create_topic: bool = True,
    replication_factor: int = 1,
    num_partitions: int = 5,
) -> None:
    """Produces 15 messages from HN to chosen Kafka topic.

    Args:
        juju: Jubilant juju fixture
        kafka_unit_name: the kafka unit to checks logs on
        provider_unit_name: the app to grab credentials from
        topic: the desired topic to produce to
        create_topic: if the topic needs to be created
        replication_factor: replication factor of the created topic
        num_partitions: number of partitions for the topic

    Raises:
        KeyError: if missing relation data
        AssertionError: if logs aren't found for desired topic
    """
    assert juju.model
    relation_data = get_provider_data(
        model=juju.model,
        unit_name=provider_unit_name,
        owner=APP_NAME,
    )
    client = KafkaClient(
        servers=relation_data["endpoints"].split(","),
        username=relation_data["username"],
        password=relation_data["password"],
        security_protocol="SASL_PLAINTEXT",
    )

    if create_topic:
        topic_config = NewTopic(
            name=topic,
            num_partitions=num_partitions,
            replication_factor=replication_factor,
        )
        client.create_topic(topic=topic_config)

    for i in range(TEST_DEFAULT_MESSAGES):
        message = f"Message #{i}"
        client.produce_message(topic_name=topic, message_content=message)

    check_logs(juju, kafka_unit_name, topic)


def check_logs(juju: jubilant.Juju, kafka_unit_name: str, topic: str) -> None:
    """Checks if messages for a topic have been produced.

    Args:
        juju: Jubilant juju fixture
        kafka_unit_name: the kafka unit to checks logs on
        topic: the desired topic to check
    """
    logs = check_output(
        f"JUJU_MODEL={juju.model} juju ssh {kafka_unit_name} sudo -i 'find {PATHS['kafka']['DATA']}/data'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    ).splitlines()

    passed = False
    for log in logs:
        if topic in log and "index" in log:
            passed = True
            break

    assert passed, "logs not found"


def run_client_properties(juju: jubilant.Juju) -> str:
    """Runs command requiring admin permissions, authenticated with bootstrap-server."""
    bootstrap_server = f"{get_unit_ipv4_address(juju.model, 'kafka/0')}:19093"
    result = check_output(
        f"JUJU_MODEL={juju.model} juju ssh kafka/0 sudo -i 'charmed-kafka.configs --bootstrap-server {bootstrap_server} --describe --all --command-config {PATHS['kafka']['CONF']}/client.properties --entity-type users'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return result


def set_mtls_client_acls(juju: jubilant.Juju, bootstrap_server: str) -> str:
    """Adds ACLs for principal `User:client` and `TEST-TOPIC`."""
    result = check_output(
        f"JUJU_MODEL={juju.model} juju ssh kafka/0 sudo -i 'sudo charmed-kafka.acls --bootstrap-server {bootstrap_server} --add --allow-principal=User:client --operation READ --operation WRITE --operation CREATE --topic TEST-TOPIC --command-config {PATHS['kafka']['CONF']}/client.properties'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return result


def create_test_topic(juju: jubilant.Juju, bootstrap_server: str) -> str:
    """Creates `test` topic and adds ACLs for principal `User:*`."""
    _ = check_output(
        f"JUJU_MODEL={juju.model} juju ssh kafka/0 sudo -i 'sudo charmed-kafka.topics --bootstrap-server {bootstrap_server} --command-config {PATHS['kafka']['CONF']}/client.properties -create -topic test'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    result = check_output(
        f"JUJU_MODEL={juju.model} juju ssh kafka/0 sudo -i 'sudo charmed-kafka.acls --bootstrap-server {bootstrap_server} --add --allow-principal=User:* --operation READ --operation WRITE --operation CREATE --topic test --command-config {PATHS['kafka']['CONF']}/client.properties'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return result


def count_lines_with(model_full_name: str | None, unit: str, file: str, pattern: str) -> int:
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh {unit} sudo -i 'grep \"{pattern}\" {file} | wc -l'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return int(result)


def get_secret_by_label(juju: jubilant.Juju, label: str, owner: str) -> dict[str, str]:
    secrets_meta_raw = check_output(
        f"JUJU_MODEL={juju.model} juju list-secrets --format json",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    ).strip()
    secrets_meta = json.loads(secrets_meta_raw)

    for secret_id in secrets_meta:
        if owner and not secrets_meta[secret_id]["owner"] == owner:
            continue
        if secrets_meta[secret_id]["label"] == label:
            break

    secrets_data_raw = check_output(
        f"JUJU_MODEL={juju.model} juju show-secret --format json --reveal {secret_id}",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    secret_data = json.loads(secrets_data_raw)
    return secret_data[secret_id]["content"]["Data"]


def search_secrets(juju: jubilant.Juju, owner: str, search_key: str) -> str:
    secrets_meta_raw = check_output(
        f"JUJU_MODEL={juju.model} juju list-secrets --format json",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    ).strip()
    secrets_meta = json.loads(secrets_meta_raw)

    for secret_id in secrets_meta:
        if owner and not secrets_meta[secret_id]["owner"] == owner:
            continue

        secrets_data_raw = check_output(
            f"JUJU_MODEL={juju.model} juju show-secret --format json --reveal {secret_id}",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )

        secret_data = json.loads(secrets_data_raw)
        if search_key in secret_data[secret_id]["content"]["Data"]:
            return secret_data[secret_id]["content"]["Data"][search_key]

    return ""


def show_unit(model: str, unit_name: str) -> Any:
    result = check_output(
        f"JUJU_MODEL={model} juju show-unit {unit_name}",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return yaml.safe_load(result)


def get_client_usernames(juju: jubilant.Juju, owner: str = APP_NAME) -> set[str]:
    app_secret = get_secret_by_label(juju, label=f"cluster.{owner}.app", owner=owner)

    usernames = set()
    for key in app_secret.keys():
        if "password" in key:
            usernames.add(key.split("-")[0])
        if "relation" in key:
            usernames.add(key)

    return usernames


def get_provider_data(
    model: str,
    owner: str,
    unit_name: str,
    relation_name: str = "kafka-client",
    relation_interface: str = "kafka-client-admin",
) -> dict[str, str]:
    _juju = jubilant.Juju(model=model)

    unit_data = show_unit(model, unit_name)

    provider_relation_data = {}
    for info in unit_data[unit_name]["relation-info"]:
        if info["endpoint"] == relation_interface:
            provider_relation_data["relation-id"] = info["relation-id"]

            # initially collects all non-secret keys
            provider_relation_data.update(dict(info["application-data"]))

    user_secret = get_secret_by_label(
        _juju,
        label=f"{relation_name}.{provider_relation_data['relation-id']}.user.secret",
        owner=owner,
    )

    tls_secret = get_secret_by_label(
        _juju,
        label=f"{relation_name}.{provider_relation_data['relation-id']}.tls.secret",
        owner=owner,
    )

    # overrides to secret keys if found
    return provider_relation_data | user_secret | tls_secret


def get_relation_data(
    juju: jubilant.Juju,
    unit: str,
    endpoint: str,
    key: Literal["application-data", "local-unit"] = "application-data",
):
    show_unit = json.loads(juju.cli("show-unit", "--format", "json", unit))
    d_relations = show_unit[unit]["relation-info"]
    for relation in d_relations:
        if relation["endpoint"] == endpoint:
            return relation[key]
    raise Exception("No relation found!")


def get_address(juju: jubilant.Juju, app_name=APP_NAME, unit_num=0) -> str:
    """Get the address for a unit."""
    status = juju.status()
    return status.apps[app_name].units[f"{app_name}/{unit_num}"].public_address


def get_machine(juju: jubilant.Juju, app_name=APP_NAME, unit_num=0) -> str:
    """Get the machine_id for a unit."""
    status = juju.status()
    return status.apps[app_name].units[f"{app_name}/{unit_num}"].machine


def balancer_exporter_is_up(model_full_name: str | None, app_name: str) -> bool:
    check_output(
        f"JUJU_MODEL={model_full_name} juju ssh {app_name}/leader sudo -i 'curl http://localhost:{JMX_CC_PORT}/metrics'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )
    return True


def balancer_is_running(model_full_name: str | None, app_name: str) -> bool:
    check_output(
        f"JUJU_MODEL={model_full_name} juju ssh {app_name}/leader sudo -i 'curl http://localhost:9090/kafkacruisecontrol/state'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )
    return True


def balancer_is_secure(juju: jubilant.Juju, app_name: str) -> bool:
    model_full_name = juju.model
    err_401 = "Error 401 Unauthorized"
    unauthorized_ok = err_401 in check_output(
        f"JUJU_MODEL={model_full_name} juju ssh {app_name}/leader sudo -i 'curl http://localhost:9090/kafkacruisecontrol/state'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    pwd = get_secret_by_label(juju=juju, label=f"{PEER}.{app_name}.app", owner=app_name)[
        "balancer-password"
    ]
    authorized_ok = err_401 not in check_output(
        f"JUJU_MODEL={model_full_name} juju ssh {app_name}/leader sudo -i 'curl http://localhost:9090/kafkacruisecontrol/state'"
        f" -u {BALANCER_WEBSERVER_USER}:{pwd}",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )
    return all((unauthorized_ok, authorized_ok))


@retry(
    wait=wait_fixed(20),  # long enough to not overwhelm the API
    stop=stop_after_attempt(360),  # give it 120 minutes to load
    retry=retry_if_result(lambda result: result is False),
    retry_error_callback=lambda _: False,
)
def balancer_is_ready(juju: jubilant.Juju, app_name: str) -> bool:
    pwd = get_secret_by_label(juju=juju, label=f"{PEER}.{app_name}.app", owner=app_name)[
        "balancer-password"
    ]

    try:
        monitor_state = check_output(
            f"JUJU_MODEL={juju.model} juju ssh {app_name}/leader sudo -i 'curl http://localhost:9090/kafkacruisecontrol/state?json=True'"
            f" -u {BALANCER_WEBSERVER_USER}:{pwd}",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )
        monitor_state_json = json.loads(monitor_state).get("MonitorState", {})
    except (json.JSONDecodeError, CalledProcessError) as e:
        logger.error(e)
        return False

    logger.debug(f"{monitor_state_json=}")

    return all(
        [
            monitor_state_json.get("numMonitoredWindows", 0),
            monitor_state_json.get("numValidPartitions", 0),
            monitor_state_json.get("state", "SAMPLING") in ["READY", "RUNNING"],
        ]
    )


@retry(
    wait=wait_fixed(20),  # long enough to not overwhelm the API
    stop=stop_after_attempt(6),
    reraise=True,
)
def get_kafka_broker_state(juju: jubilant.Juju, app_name: str) -> JSON:
    pwd = get_secret_by_label(juju=juju, label=f"{PEER}.{app_name}.app", owner=app_name)[
        "balancer-password"
    ]
    broker_state = check_output(
        f"JUJU_MODEL={juju.model} juju ssh {app_name}/leader sudo -i 'curl http://localhost:9090/kafkacruisecontrol/kafka_cluster_state?json=True'"
        f" -u {BALANCER_WEBSERVER_USER}:{pwd}",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    try:
        broker_state_json = json.loads(broker_state).get("KafkaBrokerState", {})
    except json.JSONDecodeError as e:
        logger.error(e)
        return False

    logger.debug(f"{broker_state_json=}")
    return broker_state_json


def get_replica_count_by_broker_id(juju: jubilant.Juju, app_name: str) -> dict[str, Any]:
    broker_state_json = get_kafka_broker_state(juju, app_name)
    return broker_state_json.get("ReplicaCountByBrokerId", {})


@retry(
    wait=wait_fixed(20),
    stop=stop_after_attempt(6),
    reraise=True,
)
def kraft_quorum_status(
    juju: jubilant.Juju, unit_name: str, bootstrap_controller: str, verbose: bool = True
) -> dict[int, KRaftUnitStatus]:
    """Returns a dict mapping of unit ID to KRaft unit status based on `kafka-metadata-quorum.sh` utility's output."""
    result = check_output(
        f"JUJU_MODEL={juju.model} juju ssh {unit_name} sudo -i 'charmed-kafka.metadata-quorum  --command-config {PATHS['kafka']['CONF']}/kraft-client.properties --bootstrap-controller {bootstrap_controller} describe --replication'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )
    # parse `kafka-metadata-quorum.sh` output
    # NodeId  DirectoryId  LogEndOffset  Lag  LastFetchTimestamp  LastCaughtUpTimestamp  Status
    unit_status: dict[int, str] = {}
    for line in result.split("\n"):
        fields = [c.strip() for c in line.split("\t")]
        try:
            unit_status[int(fields[0])] = KRaftUnitStatus(fields[6])
        except (ValueError, IndexError):
            continue

    if verbose:
        print(unit_status)

    return unit_status


def list_truststore_aliases(
    juju: jubilant.Juju, unit: str = f"{APP_NAME}/0", scope: Literal["client", "peer"] = "client"
) -> list[str]:
    truststore_password = extract_truststore_password(juju=juju, unit_name=unit)

    try:
        result = check_output(
            f"JUJU_MODEL={juju.model} juju ssh {unit} sudo -i 'charmed-kafka.keytool -list -keystore /var/snap/charmed-kafka/current/etc/kafka/{scope}-truststore.jks -storepass {truststore_password}'",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )
    except CalledProcessError as e:
        logger.error(f"{e.output=}, {e.stdout=}, {e.stderr=}")
        raise e

    trusted_aliases = []
    for line in result.splitlines():
        if "trustedCertEntry" not in line:
            continue

        trusted_aliases.append(line.split(",")[0])

    return trusted_aliases


def check_log_dirs(model: str | None):
    bootstrap_server = f"{get_unit_ipv4_address(model, 'kafka/0')}:19093"
    command = (
        f"JUJU_MODEL={model} juju ssh kafka/0 sudo -i 'charmed-kafka.log-dirs --command-config {PATHS['kafka']['CONF']}/client.properties --bootstrap-server {bootstrap_server} --describe'",
    )

    result = check_output(
        command,
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return BalancerManager._parse_log_dirs_output(result)
