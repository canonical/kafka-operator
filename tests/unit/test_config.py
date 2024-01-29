#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from pathlib import Path
from unittest.mock import PropertyMock, mock_open, patch

import pytest
import yaml
from ops.testing import Harness

from charm import KafkaCharm
from literals import (
    ADMIN_USER,
    CHARM_KEY,
    DEPENDENCIES,
    INTER_BROKER_USER,
    INTERNAL_USERS,
    JMX_EXPORTER_PORT,
    JVM_MEM_MAX_GB,
    JVM_MEM_MIN_GB,
    PEER,
    ZK,
)
from managers.config import KafkaConfigManager

CONFIG = str(yaml.safe_load(Path("./config.yaml").read_text()))
ACTIONS = str(yaml.safe_load(Path("./actions.yaml").read_text()))
METADATA = str(yaml.safe_load(Path("./metadata.yaml").read_text()))


@pytest.fixture
def harness():
    harness = Harness(KafkaCharm, meta=METADATA)
    harness.add_relation("restart", CHARM_KEY)
    harness._update_config(
        {
            "log_retention_ms": "-1",
            "compression_type": "producer",
        }
    )
    harness.begin()
    return harness


def test_all_storages_in_log_dirs(harness: Harness):
    """Checks that the log.dirs property updates with all available storages."""
    storage_metadata = harness.charm.meta.storages["data"]
    min_storages = storage_metadata.multiple_range[0] if storage_metadata.multiple_range else 0
    with harness.hooks_disabled():
        harness.add_storage(storage_name="data", count=min_storages, attach=True)

    assert len(harness.charm.state.log_dirs.split(",")) == len(
        harness.charm.model.storages["data"]
    )


def test_internal_credentials_only_return_when_all_present(harness: Harness):
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    harness.update_relation_data(
        peer_rel_id, CHARM_KEY, {f"{INTERNAL_USERS[0]}-password": "mellon"}
    )

    assert not harness.charm.state.cluster.internal_user_credentials

    for user in INTERNAL_USERS:
        harness.update_relation_data(peer_rel_id, CHARM_KEY, {f"{user}-password": "mellon"})

    assert harness.charm.state.cluster.internal_user_credentials
    assert len(harness.charm.state.cluster.internal_user_credentials) == len(INTERNAL_USERS)


def test_log_dirs_in_server_properties(harness: Harness):
    """Checks that log.dirs are added to server_properties."""
    zk_relation_id = harness.add_relation(ZK, CHARM_KEY)
    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "chroot": "/kafka",
            "username": "moria",
            "password": "mellon",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181/kafka,2.2.2.2:2181/kafka",
            "tls": "disabled",
        },
    )
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_relation_id, "kafka/1")
    harness.update_relation_data(peer_relation_id, "kafka/0", {"private-address": "treebeard"})

    found_log_dirs = False
    with (
        patch(
            "core.models.KafkaCluster.internal_user_credentials",
            new_callable=PropertyMock,
            return_value={INTER_BROKER_USER: "fangorn", ADMIN_USER: "forest"},
        )
    ):
        for prop in harness.charm.config_manager.server_properties:
            if "log.dirs" in prop:
                found_log_dirs = True

        assert found_log_dirs


def test_listeners_in_server_properties(harness: Harness):
    """Checks that listeners are split into INTERNAL and EXTERNAL."""
    zk_relation_id = harness.add_relation(ZK, CHARM_KEY)
    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "chroot": "/kafka",
            "username": "moria",
            "password": "mellon",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181/kafka,2.2.2.2:2181/kafka",
            "tls": "disabled",
        },
    )
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_relation_id, "kafka/1")
    harness.update_relation_data(peer_relation_id, "kafka/0", {"private-address": "treebeard"})

    expected_listeners = "listeners=INTERNAL_SASL_PLAINTEXT://:19092"
    expected_advertised_listeners = (
        "advertised.listeners=INTERNAL_SASL_PLAINTEXT://treebeard:19092"
    )

    with (
        patch(
            "core.models.KafkaCluster.internal_user_credentials",
            new_callable=PropertyMock,
            return_value={INTER_BROKER_USER: "fangorn", ADMIN_USER: "forest"},
        )
    ):
        assert expected_listeners in harness.charm.config_manager.server_properties
        assert expected_advertised_listeners in harness.charm.config_manager.server_properties


def test_ssl_listeners_in_server_properties(harness: Harness):
    """Checks that listeners are added after TLS relation are created."""
    zk_relation_id = harness.add_relation(ZK, CHARM_KEY)
    # Simulate data-integrator relation
    client_relation_id = harness.add_relation("kafka-client", "app")
    harness.update_relation_data(client_relation_id, "app", {"extra-user-roles": "admin,producer"})
    client_relation_id = harness.add_relation("kafka-client", "appii")
    harness.update_relation_data(
        client_relation_id, "appii", {"extra-user-roles": "admin,consumer"}
    )

    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "chroot": "/kafka",
            "username": "moria",
            "password": "mellon",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181/kafka,2.2.2.2:2181/kafka",
            "tls": "enabled",
        },
    )
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_relation_id, "kafka/1")
    harness.update_relation_data(
        peer_relation_id,
        "kafka/0",
        {"private-address": "treebeard", "certificate": "keepitsecret"},
    )
    harness.update_relation_data(peer_relation_id, "kafka", {"tls": "enabled", "mtls": "enabled"})

    expected_listeners = (
        "listeners=INTERNAL_SASL_SSL://:19093,CLIENT_SASL_SSL://:9093,CLIENT_SSL://:9094"
    )
    expected_advertised_listeners = "advertised.listeners=INTERNAL_SASL_SSL://treebeard:19093,CLIENT_SASL_SSL://treebeard:9093,CLIENT_SSL://treebeard:9094"

    with (
        patch(
            "core.models.KafkaCluster.internal_user_credentials",
            new_callable=PropertyMock,
            return_value={INTER_BROKER_USER: "fangorn", ADMIN_USER: "forest"},
        )
    ):
        assert expected_listeners in harness.charm.config_manager.server_properties
        assert expected_advertised_listeners in harness.charm.config_manager.server_properties


def test_zookeeper_config_succeeds_fails_config(harness: Harness):
    """Checks that no ZK config is returned if missing field."""
    zk_relation_id = harness.add_relation(ZK, CHARM_KEY)
    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "chroot": "/kafka",
            "username": "moria",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181,2.2.2.2:2181/kafka",
            "tls": "disabled",
        },
    )
    assert not harness.charm.state.zookeeper.zookeeper_connected


def test_zookeeper_config_succeeds_valid_config(harness: Harness):
    """Checks that ZK config is returned if all fields."""
    zk_relation_id = harness.add_relation(ZK, CHARM_KEY)
    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "chroot": "/kafka",
            "username": "moria",
            "password": "mellon",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181/kafka,2.2.2.2:2181/kafka",
            "tls": "disabled",
        },
    )
    assert harness.charm.state.zookeeper.connect == "1.1.1.1:2181,2.2.2.2:2181/kafka"
    assert harness.charm.state.zookeeper.zookeeper_connected


def test_kafka_opts(harness: Harness):
    """Checks necessary args for KAFKA_OPTS."""
    args = harness.charm.config_manager.kafka_opts
    assert "-Djava.security.auth.login.config" in args
    assert "KAFKA_OPTS" in args


@pytest.mark.parametrize(
    "profile,expected",
    [("production", JVM_MEM_MAX_GB), ("testing", JVM_MEM_MIN_GB)],
)
def test_heap_opts(harness: Harness, profile, expected):
    """Checks necessary args for KAFKA_HEAP_OPTS."""
    # Harness doesn't reinitialize KafkaCharm when calling update_config, which means that
    # self.config is not passed again to KafkaConfigManager
    harness.update_config({"profile": profile})
    conf_manager = KafkaConfigManager(
        harness.charm.state, harness.charm.workload, harness.charm.config, "1"
    )
    args = conf_manager.heap_opts

    assert f"Xms{expected}G" in args
    assert f"Xmx{expected}G" in args
    assert "KAFKA_HEAP_OPTS" in args


def test_jmx_opts(harness: Harness):
    """Checks necessary args for KAFKA_JMX_OPTS."""
    args = harness.charm.config_manager.jmx_opts
    assert "-javaagent:" in args
    assert args.split(":")[1].split("=")[-1] == str(JMX_EXPORTER_PORT)
    assert "KAFKA_JMX_OPTS" in args


def test_set_environment(harness: Harness):
    """Checks all necessary env-vars are written to /etc/environment."""
    with (
        patch("workload.KafkaWorkload.write") as patched_write,
        patch("core.workload.WorkloadBase.set_snap_ownership"),
        patch("builtins.open", mock_open()),
        patch("shutil.chown"),
    ):
        harness.charm.config_manager.set_environment()

        for call in patched_write.call_args_list:
            assert "KAFKA_OPTS" in call.kwargs.get("content", "")
            assert "KAFKA_LOG4J_OPTS" in call.kwargs.get("content", "")
            assert "KAFKA_JMX_OPTS" in call.kwargs.get("content", "")
            assert "KAFKA_HEAP_OPTS" in call.kwargs.get("content", "")
            assert "KAFKA_JVM_PERFORMANCE_OPTS" in call.kwargs.get("content", "")
            assert "/etc/environment" == call.kwargs.get("path", "")


# def test_map_env_populated():
#     example_env = [
#         "KAFKA_OPTS=orcs -Djava=wargs -Dkafka=goblins",
#         "SERVER_JVMFLAGS=dwarves -Djava=elves -Dzookeeper=men",
#     ]
#     env = map_env(env=example_env)

#     assert len(env) == 2
#     assert sorted(env.keys()) == sorted(["KAFKA_OPTS", "SERVER_JVMFLAGS"])

#     for value in env.values():
#         assert isinstance(value, str)
#         # checks handles multiple equals signs in value
#         assert len(value.split()) == 3


# def test_map_env_empty_item():
#     # we get this after reading the default /etc/environment from a stock 22.04 because of safe_get_file,
#     # see: https://github.com/verterok/zookeeper-operator/blob/fix-invalid-etc-env/src/utils.py#L44
#     example_env = [
#         'PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games:/snap/bin"',
#         "",
#     ]
#     env = map_env(env=example_env)

#     assert len(env) == 1
#     assert sorted(env.keys()) == sorted(["PATH"])

#     for value in env.values():
#         assert isinstance(value, str)


# def test_get_env_empty():
#     with patch("utils.safe_get_file", return_value=[]):
#         assert not get_env()
#         assert get_env() == {}


# def test_update_env():
#     example_get_env = {
#         "KAFKA_OPTS": "orcs -Djava=wargs -Dkafka=goblins",
#         "SERVER_JVMFLAGS": "dwarves -Djava=elves -Dzookeeper=men",
#     }
#     example_update_env = {
#         "SERVER_JVMFLAGS": "gimli -Djava=legolas -Dzookeeper=aragorn",
#     }

#     with (
#         patch("utils.get_env", return_value=example_get_env),
#         patch("utils.safe_write_to_file") as safe_write,
#     ):
#         update_env(env=example_update_env)

#         assert all(
#             updated in safe_write.call_args.kwargs["content"]
#             for updated in ["gimli", "legolas", "aragorn"]
#         )
#         assert "KAFKA_OPTS" in safe_write.call_args.kwargs["content"]
#         assert safe_write.call_args.kwargs["path"] == "/etc/environment"
#         assert safe_write.call_args.kwargs["mode"] == "w"


def test_bootstrap_server(harness: Harness):
    """Checks the bootstrap-server property setting."""
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_relation_id, "kafka/1")
    harness.update_relation_data(peer_relation_id, "kafka/0", {"private-address": "treebeard"})
    harness.update_relation_data(peer_relation_id, "kafka/1", {"private-address": "shelob"})

    assert len(harness.charm.state.bootstrap_server) == 2
    for server in harness.charm.state.bootstrap_server:
        assert "9092" in server


def test_default_replication_properties_less_than_three(harness: Harness):
    """Checks replication property defaults updates with units < 3."""
    assert "num.partitions=1" in harness.charm.config_manager.default_replication_properties
    assert (
        "default.replication.factor=1"
        in harness.charm.config_manager.default_replication_properties
    )
    assert "min.insync.replicas=1" in harness.charm.config_manager.default_replication_properties


def test_default_replication_properties_more_than_three(harness: Harness):
    """Checks replication property defaults updates with units > 3."""
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_relation_id, "kafka/1")
    harness.add_relation_unit(peer_relation_id, "kafka/2")
    harness.add_relation_unit(peer_relation_id, "kafka/3")
    harness.add_relation_unit(peer_relation_id, "kafka/4")
    harness.add_relation_unit(peer_relation_id, "kafka/5")

    assert "num.partitions=3" in harness.charm.config_manager.default_replication_properties
    assert (
        "default.replication.factor=3"
        in harness.charm.config_manager.default_replication_properties
    )
    assert "min.insync.replicas=2" in harness.charm.config_manager.default_replication_properties


def test_ssl_principal_mapping_rules(harness: Harness):
    """Check that a change in ssl_principal_mapping_rules is reflected in server_properties."""
    harness.add_relation(PEER, CHARM_KEY)
    zk_relation_id = harness.add_relation(ZK, CHARM_KEY)
    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "chroot": "/kafka",
            "username": "moria",
            "password": "mellon",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181/kafka,2.2.2.2:2181/kafka",
            "tls": "disabled",
        },
    )

    with (
        patch(
            "core.models.KafkaCluster.internal_user_credentials",
            new_callable=PropertyMock,
            return_value={INTER_BROKER_USER: "fangorn", ADMIN_USER: "forest"},
        )
    ):
        # Harness doesn't reinitialize KafkaCharm when calling update_config, which means that
        # self.config is not passed again to KafkaConfigManager
        harness._update_config({"ssl_principal_mapping_rules": "RULE:^(erebor)$/$1,DEFAULT"})
        conf_manager = KafkaConfigManager(
            harness.charm.state, harness.charm.workload, harness.charm.config, "1"
        )

        assert (
            "ssl.principal.mapping.rules=RULE:^(erebor)$/$1,DEFAULT"
            in conf_manager.server_properties
        )


def test_auth_properties(harness: Harness):
    """Checks necessary auth properties are present."""
    zk_relation_id = harness.add_relation(ZK, CHARM_KEY)
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.update_relation_data(
        peer_relation_id, harness.charm.app.name, {"sync_password": "mellon"}
    )
    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "chroot": "/kafka",
            "username": "moria",
            "password": "mellon",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181/kafka,2.2.2.2:2181/kafka",
            "tls": "disabled",
        },
    )

    assert "broker.id=0" in harness.charm.config_manager.auth_properties
    assert (
        f"zookeeper.connect={harness.charm.state.zookeeper.connect}"
        in harness.charm.config_manager.auth_properties
    )


def test_rack_properties(harness: Harness):
    """Checks that rack properties are added to server properties."""
    harness.add_relation(PEER, CHARM_KEY)
    zk_relation_id = harness.add_relation(ZK, CHARM_KEY)
    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "chroot": "/kafka",
            "username": "moria",
            "password": "mellon",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181/kafka,2.2.2.2:2181/kafka",
            "tls": "disabled",
        },
    )

    with (
        patch(
            "managers.config.KafkaConfigManager.rack_properties",
            new_callable=PropertyMock,
            return_value=["broker.rack=gondor-west"],
        )
    ):
        assert "broker.rack=gondor-west" in harness.charm.config_manager.server_properties


def test_inter_broker_protocol_version(harness: Harness):
    """Checks that rack properties are added to server properties."""
    harness.add_relation(PEER, CHARM_KEY)
    zk_relation_id = harness.add_relation(ZK, CHARM_KEY)
    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "chroot": "/kafka",
            "username": "moria",
            "password": "mellon",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181/kafka,2.2.2.2:2181/kafka",
            "tls": "disabled",
        },
    )
    assert len(DEPENDENCIES["kafka_service"]["version"].split(".")) == 3

    assert "inter.broker.protocol.version=3.6" in harness.charm.config_manager.server_properties


def test_super_users(harness: Harness):
    """Checks super-users property is updated for new admin clients."""
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    app_relation_id = harness.add_relation("kafka-client", "app")
    harness.update_relation_data(app_relation_id, "app", {"extra-user-roles": "admin,producer"})
    appii_relation_id = harness.add_relation("kafka-client", "appii")
    harness.update_relation_data(
        appii_relation_id, "appii", {"extra-user-roles": "admin,consumer"}
    )

    assert len(harness.charm.state.super_users.split(";")) == len(INTERNAL_USERS)

    harness.update_relation_data(
        peer_relation_id, harness.charm.app.name, {f"relation-{app_relation_id}": "mellon"}
    )

    assert len(harness.charm.state.super_users.split(";")) == (len(INTERNAL_USERS) + 1)

    harness.update_relation_data(
        peer_relation_id, harness.charm.app.name, {f"relation-{appii_relation_id}": "mellon"}
    )

    assert len(harness.charm.state.super_users.split(";")) == (len(INTERNAL_USERS) + 2)

    harness.update_relation_data(appii_relation_id, "appii", {"extra-user-roles": "consumer"})

    assert len(harness.charm.state.super_users.split(";")) == (len(INTERNAL_USERS) + 1)
