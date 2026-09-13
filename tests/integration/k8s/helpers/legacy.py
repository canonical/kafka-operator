#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import re
import socket
import subprocess
from contextlib import closing
from pathlib import Path
from subprocess import PIPE, CalledProcessError, check_output
from typing import Any, List, Literal, Set

import jubilant
import yaml
from charmlibs.interfaces.tls_certificates import PrivateKey
from kafka.admin import NewTopic
from single_kernel_kafka.core.literals import (
    ADMIN_USER,
    BALANCER_WEBSERVER_USER,
    BROKER,
    CONTROLLER_USER,
    INTERNAL_USERS,
    JMX_CC_PORT,
    KRAFT_NODE_ID_OFFSET,
    PEER,
    SECURITY_PROTOCOL_PORTS,
    KRaftUnitStatus,
)
from single_kernel_kafka.core.models import JSON
from single_kernel_kafka.lib.v0.client import KafkaClient
from single_kernel_kafka.managers.auth import Acl, AuthManager
from tenacity import (
    RetryError,
    Retrying,
    retry,
    retry_if_result,
    stop_after_attempt,
    stop_after_delay,
    wait_fixed,
)

from . import get_k8s_host_from_unit

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./k8s/metadata.yaml").read_text())
KAFKA_CONTAINER = METADATA["resources"]["kafka-image"]["upstream-source"]
APP_NAME = METADATA["name"]
CONTROLLER_NAME = "controller"
ZK_NAME = "zookeeper-k8s"
DUMMY_NAME = "app"
REL_NAME_ADMIN = "kafka-client-admin"
REL_NAME_PRODUCER = "kafka-client-producer"
TEST_DEFAULT_MESSAGES = 15
STORAGE = "data"
TLS_NAME = "self-signed-certificates"
MANUAL_TLS_NAME = "manual-tls-certificates"
CERTS_NAME = "tls-certificates-operator"
TLS_REQUIRER = "tls-certificates-requirer"
NON_REL_USERS = set(INTERNAL_USERS + [CONTROLLER_USER])
MTLS_NAME = "mtls"
DUMMY_NAME = "app"

AUTH_SECRET_NAME = "auth"
AUTH_SECRET_CONFIG_KEY = "system-users"

TLS_SECRET_NAME = "tls-pk"
TLS_SECRET_CONFIG_KEY = "tls-private-key"

KRaftMode = Literal["single", "multi"]


def load_acls(model_full_name: str | None) -> Set[Acl]:
    bootstrap_server = f'{get_k8s_host_from_unit("kafka-k8s/0")}:19093'
    container_command = f"{BROKER.paths['BIN']}/bin/kafka-acls.sh --command-config {BROKER.paths['CONF']}/client.properties --bootstrap-server {bootstrap_server} --list"

    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh --container kafka kafka-k8s/0 '{container_command}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return AuthManager._parse_acls(acls=result)


def load_super_users(model_full_name: str | None) -> List[str]:
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh --container kafka {APP_NAME}/0 'cat {BROKER.paths['CONF']}/server.properties'",
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
    bootstrap_server = f'{get_k8s_host_from_unit("kafka-k8s/0")}:19093'
    container_command = f"{BROKER.paths['BIN']}/bin/kafka-configs.sh --bootstrap-server {bootstrap_server} --describe --entity-type users --entity-name {username} --command-config {BROKER.paths['CONF']}/client.properties"
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh --container kafka kafka-k8s/0 '{container_command}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    assert f"SCRAM credential configs for user-principal '{username}' are SCRAM-SHA-512" in result


def get_user(model_full_name: str | None, username: str = "sync") -> str:
    """Get information related to a user stored on zookeeper."""
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh --container kafka {APP_NAME}/0 'cat {BROKER.paths['CONF']}/server.properties'",
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
    custom_auth = {username: password}
    secret_id = juju.add_secret(name=AUTH_SECRET_NAME, content=custom_auth)
    # grant access to our app
    juju.grant_secret(AUTH_SECRET_NAME, APP_NAME)
    # configure the app to use the secret_id
    juju.config(APP_NAME, {AUTH_SECRET_CONFIG_KEY: secret_id})


def set_tls_private_key(juju: jubilant.Juju, secret: dict[str, PrivateKey]) -> None:
    """Use the charm `tls-private-key` config option to set a PK."""
    secret_id = juju.add_secret(
        name=TLS_SECRET_NAME,
        content={unit_name: tls_pk.raw for unit_name, tls_pk in secret.items()},
    )

    # grant access to our app
    juju.grant_secret(TLS_SECRET_NAME, APP_NAME)

    # configure the app to use the secret_id
    juju.config(APP_NAME, {TLS_SECRET_CONFIG_KEY: secret_id})


def update_tls_private_key(juju: jubilant.Juju, secret: dict[str, PrivateKey]) -> None:
    """Update the `tls-private-key` config option secret to change a PK."""
    juju.update_secret(
        TLS_SECRET_NAME,
        content={unit_name: tls_pk.raw for unit_name, tls_pk in secret.items()},
    )


def remove_tls_private_key(juju: jubilant.Juju) -> None:
    """Remove the `tls-private-key` config option secret."""
    juju.config(APP_NAME, {TLS_SECRET_CONFIG_KEY: ""})


def get_actual_tls_private_key(juju: jubilant.Juju, unit_name: str) -> str:
    return check_output(
        f"JUJU_MODEL={juju.model} juju ssh --container kafka {unit_name} 'cat /etc/kafka/client-server.key'",
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


def netcat(host: str, port: int) -> bool:
    try:
        check_output(
            f"nc -zv {host} {port}",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )
        return True
    except CalledProcessError as e:
        logger.error(e)
        return False


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
        juju=juju,
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
        juju: jubilant.Juju
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
    relation_data = get_provider_data(
        juju=juju,
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
    """Produces messages from HN to chosen Kafka topic.

    Args:
        juju: jubilant.Juju
        kafka_unit_name: the kafka unit to checks logs on
        topic: the desired topic to produce to

    Raises:
        KeyError: if missing relation data
        AssertionError: if logs aren't found for desired topic
    """
    logs = check_output(
        f"JUJU_MODEL={juju.model} juju ssh --container kafka {kafka_unit_name} 'find {BROKER.paths['DATA']}/{STORAGE}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    ).splitlines()

    passed = False
    for log in logs:
        if topic in log and "index" in log:
            passed = True
            break

    assert logs and passed, "logs not found"


def run_client_properties(juju: jubilant.Juju) -> str:
    """Runs command requiring admin permissions, authenticated with bootstrap-server."""
    bootstrap_server = f'{get_k8s_host_from_unit("kafka-k8s/0")}:19093'
    container_command = f"{BROKER.paths['BIN']}/bin/kafka-configs.sh --bootstrap-server {bootstrap_server} --describe --all --command-config {BROKER.paths['CONF']}/client.properties --entity-type users"

    result = check_output(
        f"JUJU_MODEL={juju.model} juju ssh --container kafka kafka-k8s/0 '{container_command}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return result


def set_mtls_client_acls(juju: jubilant.Juju, bootstrap_server: str) -> str:
    """Adds ACLs for principal `User:client` and `TEST-TOPIC`."""
    container_command = f"KAFKA_OPTS=-Djava.security.auth.login.config={BROKER.paths['CONF']}/zookeeper-jaas.cfg {BROKER.paths['BIN']}/bin/kafka-acls.sh --bootstrap-server {bootstrap_server} --add --allow-principal=User:client --operation READ --operation WRITE --operation CREATE --topic TEST-TOPIC --command-config {BROKER.paths['CONF']}/client.properties"

    result = check_output(
        f"JUJU_MODEL={juju.model} juju ssh --container kafka kafka-k8s/0 '{container_command}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return result


def create_test_topic(juju: jubilant.Juju, bootstrap_server: str) -> str:
    """Creates `test` topic and adds ACLs for principal `User:*`."""
    _ = check_output(
        f"JUJU_MODEL={juju.model} juju ssh --container kafka kafka-k8s/0 '{BROKER.paths['BIN']}/bin/kafka-topics.sh --bootstrap-server {bootstrap_server} --command-config {BROKER.paths['CONF']}/client.properties -create -topic test'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    result = check_output(
        f"JUJU_MODEL={juju.model} juju ssh --container kafka kafka-k8s/0 '{BROKER.paths['BIN']}/bin/kafka-acls.sh --bootstrap-server {bootstrap_server} --add --allow-principal=User:* --operation READ --operation WRITE --operation CREATE --topic test --command-config {BROKER.paths['CONF']}/client.properties'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return result


def count_lines_with(juju: jubilant.Juju, unit: str, file: str, pattern: str) -> int:
    result = check_output(
        f"JUJU_MODEL={juju.model} juju ssh --container kafka {unit} 'grep \"{pattern}\" {file} | wc -l'",
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


def show_unit(juju: jubilant.Juju, unit_name: str) -> Any:
    result = check_output(
        f"JUJU_MODEL={juju.model} juju show-unit {unit_name}",
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

    return usernames - NON_REL_USERS


def get_provider_data(
    juju: jubilant.Juju,
    owner: str,
    unit_name: str,
    relation_name: str = "kafka-client",
    relation_interface: str = "kafka-client-admin",
) -> dict[str, str]:
    unit_data = show_unit(juju, unit_name)

    provider_relation_data = {}
    for info in unit_data[unit_name]["relation-info"]:
        if info["endpoint"] == relation_interface:
            provider_relation_data["relation-id"] = info["relation-id"]

            # initially collects all non-secret keys
            provider_relation_data.update(dict(info["application-data"]))

    user_secret = get_secret_by_label(
        juju,
        label=f"{relation_name}.{provider_relation_data['relation-id']}.user.secret",
        owner=owner,
    )

    tls_secret = get_secret_by_label(
        juju,
        label=f"{relation_name}.{provider_relation_data['relation-id']}.tls.secret",
        owner=owner,
    )

    # overrides to secret keys if found
    return provider_relation_data | user_secret | tls_secret


def get_address(juju: jubilant.Juju, app_name=APP_NAME, unit_num=0) -> str:
    """Get the address for a unit."""
    status = juju.status()
    address = status.apps[app_name].units[f"{app_name}/{unit_num}"].address
    return address


def delete_pod(juju: jubilant.Juju, unit_name: str):
    check_output(
        f"kubectl delete pod {unit_name.replace('/', '-')} -n {juju.model}",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )


def get_unit_address_map(juju: jubilant.Juju, app_name: str = APP_NAME) -> dict[str, str]:
    """Returns map on unit name and host.

    Args:
        juju: jubilant.Juju
        app_name: the Juju application to get hosts from
            Defaults to `kafka-k8s`

    Returns:
        Dict of key unit name, value unit address
    """
    ips = subprocess.check_output(
        f"JUJU_MODEL={juju.model} juju status {app_name} --format json | jq '.applications | .\"{app_name}\" | .units | .. .address? // empty' | xargs | tr -d '\"'",
        shell=True,
        universal_newlines=True,
    ).split()
    hosts = subprocess.check_output(
        f'JUJU_MODEL={juju.model} juju status {app_name} --format json | jq \'.applications | ."{app_name}" | .units | keys | join(" ")\' | tr -d \'"\'',
        shell=True,
        universal_newlines=True,
    ).split()

    return dict(zip(hosts, ips))


def get_bootstrap_servers(juju: jubilant.Juju, app_name: str = APP_NAME, port: int = 9092) -> str:
    """Gets all Kafka server addresses for a given application.

    Args:
        juju: jubilant.Juju
        app_name: the Juju application to get hosts from
            Defaults to `kafka-k8s`
        port: the desired Kafka port.
            Defaults to `9092`

    Returns:
        List of Kafka server addresses and ports
    """
    return ",".join(f"{host}:{port}" for host in get_unit_address_map(juju, app_name).values())


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


def get_node_port(juju: jubilant.Juju, app_name: str, service_name: str):
    namespace = juju.model
    bootstrap_service = check_output(
        f"kubectl describe svc -n {namespace} {app_name}-bootstrap",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    bootstrap_node_port = 0
    for line in bootstrap_service.splitlines():
        logger.error(f"{line}")
        if "NodePort" in line and service_name in line:
            bootstrap_node_port = int(line.split()[-1].split("/")[0])

    return bootstrap_node_port


@retry(
    wait=wait_fixed(20),  # long enough to not overwhelm the API
    stop=stop_after_attempt(180),  # give it 60 minutes to load
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
        executor_state_json = json.loads(monitor_state).get("ExecutorState", {})
    except (json.JSONDecodeError, CalledProcessError) as e:
        logger.error(e)
        return False

    print(f"{monitor_state_json=}")
    print(f"{executor_state_json=}")

    return all(
        [
            monitor_state_json.get("numMonitoredWindows", 0),
            monitor_state_json.get("numValidPartitions", 0),
            executor_state_json.get("state", "") == "NO_TASK_IN_PROGRESS",
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

    print(f"{broker_state_json=}")

    return broker_state_json


def check_external_access_non_tls(juju: jubilant.Juju, unit_name: str):
    try:
        node_ip = check_output(
            "kubectl get nodes -o wide | awk -v OFS='\t\t' '{print $6}' | sed 1D",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        ).strip()

        # grabbing the helpful client.properties for later
        client_properties = check_output(
            f"JUJU_MODEL={juju.model} juju ssh --container kafka {unit_name} 'cat /etc/kafka/client.properties'",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        ).splitlines()

        bootstrap_node_port = get_node_port(
            juju, unit_name.split("/")[0], "sasl-plaintext-scram-bootstrap-port"
        )

    except CalledProcessError as e:
        logger.error(vars(e))
        raise e

    admin_password = ""
    for line in client_properties:
        if match := re.search(r"password\=\"(.*)\"", line):
            admin_password = match.group(1)
            break

    bootstrap_server = f"{node_ip}:{bootstrap_node_port}"

    client = KafkaClient(
        servers=[bootstrap_server],
        username=ADMIN_USER,
        password=admin_password,
        security_protocol="SASL_PLAINTEXT",
    )

    topic_config = NewTopic(
        name="HOT-TOPIC",
        num_partitions=100,
        replication_factor=1,
    )
    client.create_topic(topic=topic_config)

    internal_bootstrap_server = f"{get_k8s_host_from_unit(unit_name=unit_name)}:19093"
    topics_list = check_output(
        f"JUJU_MODEL={juju.model} juju ssh --container kafka {unit_name} '/opt/kafka/bin/kafka-topics.sh --bootstrap-server {internal_bootstrap_server} --command-config /etc/kafka/client.properties --list'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    assert "HOT-TOPIC" in topics_list


def get_replica_count_by_broker_id(juju: jubilant.Juju, app_name: str) -> dict[str, Any]:
    broker_state_json = get_kafka_broker_state(juju, app_name)
    return broker_state_json.get("ReplicaCountByBrokerId", {})


def balancer_exporter_is_up(model_full_name: str | None, app_name: str) -> bool:
    check_output(
        f"JUJU_MODEL={model_full_name} juju ssh {app_name}/leader sudo -i 'curl http://localhost:{JMX_CC_PORT}/metrics'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )
    return True


def get_mtls_nodeport(juju: jubilant.Juju):
    ports = check_output(
        f"kubectl get svc -n {juju.model} -o wide | grep bootstrap | awk '{{print $5}}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    ).split(",")

    logger.info(f"{ports=}")

    for port in ports:
        if port.startswith(str(SECURITY_PROTOCOL_PORTS["SSL", "SSL"].external)):
            return port.split(":")[1].split("/")[0]

    raise Exception("could not find mtls nodeport in bootstrap service")


@retry(
    wait=wait_fixed(20),
    stop=stop_after_attempt(6),
    reraise=True,
)
def kraft_quorum_status(
    juju: jubilant.Juju, unit_name: str, bootstrap_controller: str, verbose: bool = True
) -> dict[int, KRaftUnitStatus]:
    """Returns a dict mapping of unit ID to KRaft unit status based on `kafka-metadata-quorum.sh` utility's output."""
    try:
        result = check_output(
            f"JUJU_MODEL={juju.model} juju ssh --container kafka {unit_name} '{BROKER.paths['BIN']}/bin/kafka-metadata-quorum.sh --command-config {BROKER.paths['CONF']}/kraft-client.properties --bootstrap-controller {bootstrap_controller} describe --replication'",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )
    except CalledProcessError as e:
        logger.error(vars(e))
        raise

    # parse `kafka-metadata-quorum.sh` output
    # NodeId  DirectoryId  LogEndOffset  Lag  LastFetchTimestamp  LastCaughtUpTimestamp
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


def list_truststore_aliases(juju: jubilant.Juju, unit: str = f"{APP_NAME}/0") -> list[str]:
    truststore_password = extract_truststore_password(juju=juju, unit_name=unit)

    try:
        result = check_output(
            f"JUJU_MODEL={juju.model} juju ssh --container kafka {unit} 'keytool -list -keystore /etc/kafka/client-truststore.jks -storepass {truststore_password}'",
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


def check_socket(host: str, port: int) -> bool:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        return sock.connect_ex((host, port)) == 0


def unit_id_to_broker_id(unit_id: int) -> int:
    """Converts unit id to broker id in KRaft mode."""
    return KRAFT_NODE_ID_OFFSET + unit_id


def broker_id_to_unit_id(broker_id: int) -> int:
    """Converts broker id to unit id in KRaft mode."""
    return broker_id - KRAFT_NODE_ID_OFFSET


RelationTuple = tuple[str, str]


def get_unit_relations(juju: jubilant.Juju, unit: str) -> dict[int, RelationTuple]:
    """Parse the unit relations from show-unit command output."""
    ret = {}
    for item in show_unit(juju, unit).get("relation-info", []):
        if not (_id := item.get("relation-id")):
            continue

        endpoint = item.get("endpoint", "")
        related_endpoint = item.get("related-endpoint", "")
        ret[int(_id)] = (endpoint, related_endpoint)

    return ret


def get_relations(juju: jubilant.Juju) -> list[RelationTuple]:
    """Get current active relations in the model."""
    units = []
    status = juju.status()
    for app_status in status.apps.values():
        units.extend(app_status.units.keys())

    relations = []
    for unit in units:
        unit_relations = get_unit_relations(juju, unit)
        relations.extend(unit_relations.values())

    return relations


def relation_exited(juju: jubilant.Juju, endpoint_one: str, endpoint_two: str) -> bool:
    """Returns true if the relation between endpoint_one and endpoint_two has been removed."""
    return (endpoint_one, endpoint_two) not in get_relations(juju)


def wait_for_relation_removed_between(
    juju: jubilant.Juju, endpoint_one: str, endpoint_two: str
) -> None:
    """Wait for relation to be removed before checking if it's waiting or idle.

    Args:
        juju: running juju instance
        endpoint_one: one endpoint of the relation. Doesn't matter if it's provider or requirer.
        endpoint_two: the other endpoint of the relation.
    """
    try:
        for attempt in Retrying(stop=stop_after_delay(3 * 60), wait=wait_fixed(3)):
            with attempt:
                if relation_exited(juju, endpoint_one, endpoint_two):
                    break
    except RetryError:
        assert False, "Relation failed to exit after 3 minutes."
