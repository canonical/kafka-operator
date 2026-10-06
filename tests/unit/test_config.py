#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
import json
import logging
from pathlib import Path
from typing import cast
from unittest.mock import PropertyMock, mock_open, patch

import pytest
import yaml
from ops import CharmMeta
from ops.testing import Container, Context, PeerRelation, Relation, State, Storage

from charm import KafkaCharm
from literals import (
    ADMIN_USER,
    CONTAINER,
    DEPENDENCIES,
    INTER_BROKER_USER,
    INTERNAL_USERS,
    JMX_CC_PORT,
    JMX_EXPORTER_PORT,
    JVM_MEM_MAX_GB,
    JVM_MEM_MIN_GB,
    OAUTH_REL_NAME,
    PEER,
    PEER_CLUSTER_ORCHESTRATOR_RELATION,
    REL_NAME,
    SUBSTRATE,
    ZK,
)

pytestmark = pytest.mark.broker


logger = logging.getLogger(__name__)


CONFIG = yaml.safe_load(Path("./config.yaml").read_text())
ACTIONS = yaml.safe_load(Path("./actions.yaml").read_text())
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())


@pytest.fixture()
def charm_configuration():
    """Enable direct mutation on configuration dict."""
    return json.loads(json.dumps(CONFIG))


@pytest.fixture()
def base_state():
    if SUBSTRATE == "k8s":
        state = State(leader=True, containers=[Container(name=CONTAINER, can_connect=True)])

    else:
        state = State(leader=True)

    return state


@pytest.fixture()
def ctx() -> Context:
    ctx = Context(KafkaCharm, meta=METADATA, config=CONFIG, actions=ACTIONS, unit_id=0)
    return ctx


def test_all_storages_in_log_dirs(ctx: Context, base_state: State) -> None:
    """Checks that the log.dirs property updates with all available storages."""
    # Given
    storage_medatada = CharmMeta(METADATA).storages["data"]
    min_storages = storage_medatada.multiple_range[0] if storage_medatada.multiple_range else 1
    storages = [Storage("data") for _ in range(min_storages)]
    state_in = dataclasses.replace(base_state, storages=storages)

    # When
    with ctx(ctx.on.storage_attached(storages[0]), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)

        # Then
        assert len(charm.state.log_dirs.split(",")) == len(charm.model.storages["data"])


def test_internal_credentials_only_return_when_all_present(
    ctx: Context, base_state: State, passwords_data: dict[str, str]
) -> None:
    # Given
    cluster_peer_incomplete = PeerRelation(
        PEER, PEER, local_app_data={f"{INTERNAL_USERS[0]}": "mellon"}
    )
    state_incomplete = dataclasses.replace(base_state, relations=[cluster_peer_incomplete])
    cluster_peer_complete = PeerRelation(PEER, PEER, local_app_data=passwords_data)
    state_complete = dataclasses.replace(base_state, relations=[cluster_peer_complete])

    # When
    with ctx(ctx.on.start(), state_incomplete) as manager:
        charm = cast(KafkaCharm, manager.charm)

        # Then
        assert not charm.state.cluster.internal_user_credentials

    # When
    with ctx(ctx.on.start(), state_complete) as manager:
        charm = cast(KafkaCharm, manager.charm)

        # Then
        assert charm.state.cluster.internal_user_credentials
        assert len(charm.state.cluster.internal_user_credentials) == len(INTERNAL_USERS)


def test_log_dirs_in_server_properties(ctx: Context, base_state: State) -> None:
    """Checks that log.dirs are added to server_properties."""
    # Given
    found_log_dirs = False
    state_in = base_state

    # When
    with (ctx(ctx.on.config_changed(), state_in) as manager,):
        charm = cast(KafkaCharm, manager.charm)
        for prop in charm.broker.config_manager.server_properties:
            if "log.dirs" in prop:
                found_log_dirs = True

    # Then
    assert found_log_dirs


def test_listeners_in_server_properties(
    charm_configuration: dict, base_state: State, zk_data: dict[str, str]
) -> None:
    """Checks that listeners are split into INTERNAL, CLIENT and EXTERNAL."""
    # Given
    charm_configuration["options"]["expose_external"]["default"] = "nodeport"
    cluster_peer = PeerRelation(PEER, PEER, local_unit_data={"private-address": "treebeard"})
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data)
    client_relation = Relation(REL_NAME, "app")
    state_in = dataclasses.replace(
        base_state, relations=[cluster_peer, zk_relation, client_relation]
    )
    ctx = Context(
        KafkaCharm, meta=METADATA, config=charm_configuration, actions=ACTIONS, unit_id=0
    )

    host = "treebeard" if SUBSTRATE == "vm" else "kafka-k8s-0.kafka-k8s-endpoints"
    sasl_pm = "SASL_PLAINTEXT_SCRAM_SHA_512"

    expected_listeners = [
        f"INTERNAL_{sasl_pm}://0.0.0.0:19092",
        f"CLIENT_{sasl_pm}://0.0.0.0:9092",
    ]
    expected_advertised_listeners = [
        f"INTERNAL_{sasl_pm}://{host}:19092",
        f"CLIENT_{sasl_pm}://{host}:9092",
    ]
    if SUBSTRATE == "k8s":
        expected_listeners += [f"EXTERNAL_{sasl_pm}://0.0.0.0:29092"]
        expected_advertised_listeners += [
            f"EXTERNAL_{sasl_pm}://1234:20000"  # values for nodeip:nodeport in conftest
        ]

    # When
    with (
        patch(
            "core.models.KafkaCluster.internal_user_credentials",
            new_callable=PropertyMock,
            return_value={INTER_BROKER_USER: "fangorn", ADMIN_USER: "forest"},
        ),
        patch(
            "managers.k8s.K8sManager._get_service",
        ),
        patch(
            "managers.k8s.K8sManager.get_node_port",
        ),
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)

        listeners = [
            prop
            for prop in charm.broker.config_manager.server_properties
            if prop.startswith("listeners=")
        ][0]
        advertised_listeners = [
            prop
            for prop in charm.broker.config_manager.server_properties
            if prop.startswith("advertised.listeners=")
        ][0]

    # Then
    for listener in expected_listeners:
        assert listener in listeners

    for listener in expected_advertised_listeners:
        assert listener in advertised_listeners


def test_extra_listeners_in_server_properties(
    charm_configuration: dict, base_state: State, zk_data: dict[str, str]
):
    """Checks that the extra-listeners are properly set from config."""
    # Given
    charm_configuration["options"]["extra_listeners"][
        "default"
    ] = "worker-{unit}.foo.com:30000,worker-{unit}.bar.com:40000"
    cluster_peer = PeerRelation(PEER, PEER, local_unit_data={"private-address": "treebeard"})
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data)
    client_relation = Relation(
        REL_NAME, "app", remote_app_data={"extra-user-roles": "admin,producer"}
    )
    state_in = dataclasses.replace(
        base_state, relations=[cluster_peer, zk_relation, client_relation]
    )
    ctx = Context(
        KafkaCharm, meta=METADATA, config=charm_configuration, actions=ACTIONS, unit_id=0
    )
    expected_listener_names = {
        "INTERNAL_SASL_PLAINTEXT_SCRAM_SHA_512",
        "CLIENT_SASL_PLAINTEXT_SCRAM_SHA_512",
        "CLIENT_SSL_SSL",
        "EXTRA_SASL_PLAINTEXT_SCRAM_SHA_512_0",
        "EXTRA_SASL_PLAINTEXT_SCRAM_SHA_512_1",
        "EXTRA_SSL_SSL_0",
        "EXTRA_SSL_SSL_1",
    }

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)

        # Then
        # 2 extra, 1 internal, 1 client
        assert len(charm.broker.config_manager.all_listeners) == 4

    # Adding SSL
    cluster_peer = dataclasses.replace(cluster_peer, local_app_data={"tls": "enabled"})
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, client_relation])

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)

        # Then
        # 2 extra, 1 internal, 1 client
        assert len(charm.broker.config_manager.all_listeners) == 4

    # Adding SSL
    cluster_peer = dataclasses.replace(
        cluster_peer, local_app_data={"tls": "enabled", "mtls": "enabled"}
    )
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, client_relation])

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)

        # Then
        # 2 extra sasl_ssl, 2 extra ssl, 1 internal, 2 client
        assert len(charm.broker.config_manager.all_listeners) == 7

        advertised_listeners_prop = ""
        for prop in charm.broker.config_manager.server_properties:
            if "advertised.listener" in prop:
                advertised_listeners_prop = prop

        # validating every expected listener is present
        for name in expected_listener_names:
            assert name in advertised_listeners_prop

        # validating their allocated ports are expected
        ports = []
        for listener in advertised_listeners_prop.split("=")[1].split(","):
            name, _, port = listener.split(":")

            if name.endswith("_0") or name.endswith("_1"):
                # verifying allocation uses the baseport
                digit = 10**4
                assert int(port) // digit * digit in (30000, 40000)

                # verifying allocation is in steps of 100
                digit = 10**2
                assert int(port) // digit * digit in (39000, 39100, 49000, 49100)

                # verifying all ports are unique
                assert port not in ports
                ports.append(port)


def test_oauth_client_listeners_in_server_properties(ctx: Context, base_state: State) -> None:
    """Checks that oauth client listeners are properly set when a relating through oauth."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_unit_data={"private-address": "treebeard"})
    oauth_relation = Relation(
        OAUTH_REL_NAME,
        "hydra",
        remote_app_data={
            "issuer_url": "issuer",
            "jwks_endpoint": "jwks",
            "authorization_endpoint": "authz",
            "token_endpoint": "token",
            "introspection_endpoint": "introspection",
            "userinfo_endpoint": "userinfo",
            "scope": "scope",
            "jwt_access_token": "False",
        },
    )
    client_relation = Relation(
        REL_NAME, "app", remote_app_data={"extra-user-roles": "admin,producer"}
    )
    state_in = dataclasses.replace(
        base_state, relations=[cluster_peer, oauth_relation, client_relation]
    )

    host = "treebeard" if SUBSTRATE == "vm" else "kafka-k8s-0.kafka-k8s-endpoints"
    internal_protocol, internal_port = "INTERNAL_SASL_PLAINTEXT_SCRAM_SHA_512", "19092"
    scram_client_protocol, scram_client_port = "CLIENT_SASL_PLAINTEXT_SCRAM_SHA_512", "9092"
    oauth_client_protocol, oauth_client_port = "CLIENT_SASL_PLAINTEXT_OAUTHBEARER", "9095"

    expected_listeners = (
        f"listeners={internal_protocol}://0.0.0.0:{internal_port},"
        f"{scram_client_protocol}://0.0.0.0:{scram_client_port},"
        f"{oauth_client_protocol}://0.0.0.0:{oauth_client_port}"
    )
    expected_advertised_listeners = (
        f"advertised.listeners={internal_protocol}://{host}:{internal_port},"
        f"{scram_client_protocol}://{host}:{scram_client_port},"
        f"{oauth_client_protocol}://{host}:{oauth_client_port}"
    )

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)

        # Then
        assert expected_listeners in charm.broker.config_manager.server_properties
        assert expected_advertised_listeners in charm.broker.config_manager.server_properties


def test_ssl_listeners_in_server_properties(
    ctx: Context, base_state: State, zk_data: dict[str, str], patched_exec
) -> None:
    """Checks that listeners are added after TLS relation are created."""
    patched_exec.return_value = ""
    # Given
    cluster_peer = PeerRelation(
        PEER,
        PEER,
        local_unit_data={"private-address": "treebeard", "certificate": "keepitsecret"},
        local_app_data={"tls": "enabled", "mtls": "enabled"},
    )
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data | {"tls": "enabled"})
    # Simulate data-integrator relation
    client_relation = Relation(
        REL_NAME, "app", remote_app_data={"extra-user-roles": "admin,producer"}
    )
    client_ii_relation = Relation(
        REL_NAME, "appii", remote_app_data={"extra-user-roles": "admin,consumer"}
    )
    state_in = dataclasses.replace(
        base_state, relations=[cluster_peer, zk_relation, client_relation, client_ii_relation]
    )

    host = "treebeard" if SUBSTRATE == "vm" else "kafka-k8s-0.kafka-k8s-endpoints"
    sasl_pm = "SASL_SSL_SCRAM_SHA_512"
    ssl_pm = "SSL_SSL"
    expected_listeners = f"listeners=INTERNAL_{sasl_pm}://0.0.0.0:19093,CLIENT_{sasl_pm}://0.0.0.0:9093,CLIENT_{ssl_pm}://0.0.0.0:9094"
    expected_advertised_listeners = f"advertised.listeners=INTERNAL_{sasl_pm}://{host}:19093,CLIENT_{sasl_pm}://{host}:9093,CLIENT_{ssl_pm}://{host}:9094"

    # When
    with (
        patch(
            "core.models.KafkaCluster.internal_user_credentials",
            new_callable=PropertyMock,
            return_value={INTER_BROKER_USER: "fangorn", ADMIN_USER: "forest"},
        ),
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)

        # Then
        assert expected_listeners in charm.broker.config_manager.server_properties
        assert expected_advertised_listeners in charm.broker.config_manager.server_properties


def test_zookeeper_config_succeeds_fails_config(ctx: Context, base_state: State) -> None:
    """Checks that no ZK config is returned if missing field."""
    # Given
    zk_relation = Relation(
        ZK,
        ZK,
        remote_app_data={
            "database": "/kafka",
            "chroot": "/kafka",
            "username": "moria",
            "endpoints": "1.1.1.1:2181,2.2.2.2:2181",
            "uris": "1.1.1.1:2181,2.2.2.2:2181/kafka",
            "tls": "disabled",
        },
    )
    state_in = dataclasses.replace(base_state, relations=[zk_relation])

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)

        # Then
        assert not charm.state.zookeeper.zookeeper_connected


def test_zookeeper_config_succeeds_valid_config(ctx: Context, base_state: State) -> None:
    """Checks that ZK config is returned if all fields."""
    # Given
    zk_relation = Relation(
        ZK,
        ZK,
        remote_app_data={
            "database": "/kafka",
            "chroot": "/kafka",
            "username": "moria",
            "password": "mellon",
            "endpoints": "1.1.1.1:2181,2.2.2.2:2181",
            "uris": "1.1.1.1:2181,2.2.2.2:2181/kafka",
            "tls": "disabled",
        },
    )
    state_in = dataclasses.replace(base_state, relations=[zk_relation])

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)

        # Then
        assert charm.state.zookeeper.zookeeper_connected
        assert charm.state.zookeeper.connect == "1.1.1.1:2181,2.2.2.2:2181/kafka"


def test_kafka_opts(ctx: Context, base_state: State) -> None:
    """Checks necessary args for KAFKA_OPTS."""
    # Given
    state_in = base_state

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)

        # Then
        args = charm.broker.config_manager.kafka_opts
        assert "-Djava.security.auth.login.config" in args
        assert "KAFKA_OPTS" in args


@pytest.mark.parametrize(
    "profile,expected",
    [("production", JVM_MEM_MAX_GB), ("testing", JVM_MEM_MIN_GB)],
)
def test_heap_opts(
    charm_configuration: dict, base_state: State, profile: str, expected: int
) -> None:
    """Checks necessary args for KAFKA_HEAP_OPTS."""
    # Given
    charm_configuration["options"]["profile"]["default"] = profile
    ctx = Context(
        KafkaCharm, meta=METADATA, config=charm_configuration, actions=ACTIONS, unit_id=0
    )
    state_in = base_state

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)

        args = charm.broker.config_manager.heap_opts

    # Then
    assert f"Xms{expected}G" in args
    assert f"Xmx{expected}G" in args
    assert "KAFKA_HEAP_OPTS" in args


def test_kafka_jmx_opts(ctx: Context, base_state: State) -> None:
    """Checks necessary args for KAFKA_JMX_OPTS."""
    # Given
    state_in = base_state

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)
        args = charm.broker.config_manager.kafka_jmx_opts

    # Then
    assert "-javaagent:" in args
    assert args.split(":")[1].split("=")[-1] == str(JMX_EXPORTER_PORT)
    assert "KAFKA_JMX_OPTS" in args


def test_cc_jmx_opts(ctx: Context, base_state: State) -> None:
    """Checks necessary args for CC_JMX_OPTS."""
    # Given
    state_in = base_state

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)
        args = charm.broker.config_manager.cc_jmx_opts

    # Then
    assert "-javaagent:" in args
    assert args.split(":")[1].split("=")[-1] == str(JMX_CC_PORT)
    assert "CC_JMX_OPTS" in args


def test_set_environment(ctx: Context, base_state: State) -> None:
    """Checks all necessary env-vars are written to /etc/environment."""
    # Given
    state_in = base_state

    # When
    with (
        patch("workload.KafkaWorkload.write") as patched_write,
        patch("builtins.open", mock_open()),
        patch("shutil.chown"),
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)
        charm.broker.config_manager.set_environment()

    # Then
    for call in patched_write.call_args_list:
        assert "KAFKA_OPTS" in call.kwargs.get("content", "")
        assert "KAFKA_LOG4J_OPTS" in call.kwargs.get("content", "")
        assert "KAFKA_JMX_OPTS" in call.kwargs.get("content", "")
        assert "KAFKA_HEAP_OPTS" in call.kwargs.get("content", "")
        assert "KAFKA_JVM_PERFORMANCE_OPTS" in call.kwargs.get("content", "")
        assert "/etc/environment" == call.kwargs.get("path", "")


def test_bootstrap_server(ctx: Context, base_state: State) -> None:
    """Checks the bootstrap-server property setting."""
    # Given
    cluster_peer = PeerRelation(
        PEER,
        PEER,
        local_unit_data={"private-address": "treebeard"},
        peers_data={1: {"private-address": "shelob"}},
    )
    state_in = dataclasses.replace(base_state, relations=[cluster_peer])

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)

        # Then
        assert len(charm.state.bootstrap_server.split(",")) == 2
        for server in charm.state.bootstrap_server.split(","):
            assert "9092" in server


def test_default_replication_properties_less_than_three(ctx: Context, base_state: State) -> None:
    """Checks replication property defaults updates with units < 3."""
    # Given
    state_in = base_state

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)

        # Then
        assert "num.partitions=1" in charm.broker.config_manager.default_replication_properties
        assert (
            "default.replication.factor=1"
            in charm.broker.config_manager.default_replication_properties
        )
        assert (
            "min.insync.replicas=1" in charm.broker.config_manager.default_replication_properties
        )


def test_default_replication_properties_more_than_three(ctx: Context, base_state: State) -> None:
    """Checks replication property defaults updates with units > 3."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER, peers_data={i: {} for i in range(1, 6)})
    state_in = dataclasses.replace(base_state, relations=[cluster_peer], planned_units=6)

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)

        # Then
        assert "num.partitions=3" in charm.broker.config_manager.default_replication_properties
        assert (
            "default.replication.factor=3"
            in charm.broker.config_manager.default_replication_properties
        )
        assert (
            "min.insync.replicas=2" in charm.broker.config_manager.default_replication_properties
        )


def test_ssl_principal_mapping_rules(
    charm_configuration: dict, base_state: State, zk_data: dict[str, str]
) -> None:
    """Check that a change in ssl_principal_mapping_rules is reflected in server_properties."""
    # Given
    charm_configuration["options"]["ssl_principal_mapping_rules"][
        "default"
    ] = "RULE:^(erebor)$/$1,DEFAULT"
    cluster_peer = PeerRelation(PEER, PEER)
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, zk_relation])
    ctx = Context(
        KafkaCharm, meta=METADATA, config=charm_configuration, actions=ACTIONS, unit_id=0
    )

    # Given
    with (
        patch(
            "core.models.KafkaCluster.internal_user_credentials",
            new_callable=PropertyMock,
            return_value={INTER_BROKER_USER: "fangorn", ADMIN_USER: "forest"},
        ),
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)

        # Then
        assert (
            "ssl.principal.mapping.rules=RULE:^(erebor)$/$1,DEFAULT"
            in charm.broker.config_manager.server_properties
        )


def test_auth_properties(ctx: Context, base_state: State, zk_data: dict[str, str]) -> None:
    """Checks necessary auth properties are present."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, zk_relation])

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)

        # Then
        assert "broker.id=0" in charm.broker.config_manager.auth_properties
        assert (
            f"zookeeper.connect={charm.state.zookeeper.connect}"
            in charm.broker.config_manager.auth_properties
        )


def test_rack_properties(ctx: Context, base_state: State, zk_data: dict[str, str]) -> None:
    """Checks that rack properties are added to server properties."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, zk_relation])

    # When
    with (
        patch(
            "managers.config.ConfigManager.rack_properties",
            new_callable=PropertyMock,
            return_value=["broker.rack=gondor-west"],
        ),
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)

        # Then
        assert "broker.rack=gondor-west" in charm.broker.config_manager.server_properties


def test_inter_broker_protocol_version(ctx: Context, base_state: State, zk_data) -> None:
    """Checks that rack properties are added to server properties."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, zk_relation])

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)

        # Then
        kafka_version: str = DEPENDENCIES.get("kafka_service", {}).get("version", "0.0.0")
        major_minor = ".".join(kafka_version.split(".")[:2])
        assert (
            f"inter.broker.protocol.version={major_minor}"
            in charm.broker.config_manager.server_properties
        )
    assert len(DEPENDENCIES["kafka_service"]["version"].split(".")) == 3


def test_super_users(ctx: Context, base_state: State) -> None:
    """Checks super-users property is updated for new admin clients."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    client_relation = Relation(
        REL_NAME, "app", remote_app_data={"extra-user-roles": "admin,producer"}
    )
    client_ii_relation = Relation(
        REL_NAME, "appii", remote_app_data={"extra-user-roles": "admin,consumer"}
    )
    state_in = dataclasses.replace(
        base_state, relations=[cluster_peer, client_relation, client_ii_relation]
    )

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)

        # Then
        assert len(charm.state.super_users.split(";")) == len(INTERNAL_USERS)

    cluster_peer = dataclasses.replace(
        cluster_peer, local_app_data={f"relation-{client_relation.id}": "mellon"}
    )
    state_in = dataclasses.replace(
        base_state, relations=[cluster_peer, client_relation, client_ii_relation]
    )

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)

        # Then
        assert len(charm.state.super_users.split(";")) == len(INTERNAL_USERS) + 1

    cluster_peer = dataclasses.replace(
        cluster_peer,
        local_app_data={
            f"relation-{client_relation.id}": "mellon",
            f"relation-{client_ii_relation.id}": "mellon",
        },
    )
    state_in = dataclasses.replace(
        base_state, relations=[cluster_peer, client_relation, client_ii_relation]
    )

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)

        # Then
        assert len(charm.state.super_users.split(";")) == len(INTERNAL_USERS) + 2

    client_ii_relation = dataclasses.replace(
        client_ii_relation, remote_app_data={"extra-user-roles": "consumer"}
    )
    state_in = dataclasses.replace(
        base_state, relations=[cluster_peer, client_relation, client_ii_relation]
    )

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)

        # Then
        assert len(charm.state.super_users.split(";")) == len(INTERNAL_USERS) + 1


def test_cruise_control_reporter_only_with_balancer(ctx: Context, base_state: State):
    # Given
    state_in = base_state
    reporters_config_value = "metric.reporters=com.linkedin.kafka.cruisecontrol.metricsreporter.CruiseControlMetricsReporter"

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)

        # Then
        # Default roles value does not include balancer
        assert reporters_config_value not in charm.broker.config_manager.server_properties

    # Given

    cluster_peer = PeerRelation(PEER, PEER)
    cluster_peer_cluster = Relation(
        PEER_CLUSTER_ORCHESTRATOR_RELATION, "peer-cluster", remote_app_data={"roles": "balancer"}
    )
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, cluster_peer_cluster])

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)

        # Then
        assert reporters_config_value in charm.broker.config_manager.server_properties
