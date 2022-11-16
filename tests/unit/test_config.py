#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from pathlib import Path

import pytest
import yaml
from ops.testing import Harness

from charm import KafkaCharm
from literals import CHARM_KEY, PEER, ZK

CONFIG = str(yaml.safe_load(Path("./config.yaml").read_text()))
ACTIONS = str(yaml.safe_load(Path("./actions.yaml").read_text()))
METADATA = str(yaml.safe_load(Path("./metadata.yaml").read_text()))


@pytest.fixture
def harness():
    harness = Harness(KafkaCharm, meta=METADATA)
    harness.add_relation("restart", CHARM_KEY)
    harness._update_config(
        {
            "offsets-retention-minutes": 10080,
            "log-retention-hours": 168,
            "auto-create-topics": False,
        }
    )
    harness.begin()
    return harness


def test_all_storages_in_server_properties_log_dirs(harness):
    """Checks that the log.dirs property updates with all available storages."""
    assert len(harness.charm.kafka_config.log_dirs) == len(
        harness.charm.model.storages["log-data"]
    )


def test_zookeeper_config_succeeds_fails_config(harness):
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
    assert harness.charm.kafka_config.zookeeper_config == {}
    assert not harness.charm.kafka_config.zookeeper_connected


def test_zookeeper_config_succeeds_valid_config(harness):
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
    assert "connect" in harness.charm.kafka_config.zookeeper_config
    assert (
        harness.charm.kafka_config.zookeeper_config["connect"] == "1.1.1.1:2181,2.2.2.2:2181/kafka"
    )
    assert harness.charm.kafka_config.zookeeper_connected


def test_extra_args(harness):
    """Checks necessary args in extra-args for KAFKA_OPTS."""
    args = "".join(harness.charm.kafka_config.extra_args)
    assert "-Djava.security.auth.login.config" in args


def test_bootstrap_server(harness):
    """Checks the bootstrap-server property setting."""
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_relation_id, "kafka/1")
    harness.update_relation_data(peer_relation_id, "kafka/0", {"private-address": "treebeard"})
    harness.update_relation_data(peer_relation_id, "kafka/1", {"private-address": "shelob"})

    assert len(harness.charm.kafka_config.bootstrap_server) == 2
    for server in harness.charm.kafka_config.bootstrap_server:
        assert "9092" in server


def test_default_replication_properties_less_than_three(harness):
    """Checks replication property defaults updates with units < 3."""
    assert "num.partitions=1" in harness.charm.kafka_config.default_replication_properties
    assert (
        "default.replication.factor=1" in harness.charm.kafka_config.default_replication_properties
    )
    assert "min.insync.replicas=1" in harness.charm.kafka_config.default_replication_properties


def test_default_replication_properties_more_than_three(harness):
    """Checks replication property defaults updates with units > 3."""
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_relation_id, "kafka/1")
    harness.add_relation_unit(peer_relation_id, "kafka/2")
    harness.add_relation_unit(peer_relation_id, "kafka/3")
    harness.add_relation_unit(peer_relation_id, "kafka/4")
    harness.add_relation_unit(peer_relation_id, "kafka/5")

    assert "num.partitions=3" in harness.charm.kafka_config.default_replication_properties
    assert (
        "default.replication.factor=3" in harness.charm.kafka_config.default_replication_properties
    )
    assert "min.insync.replicas=2" in harness.charm.kafka_config.default_replication_properties


def test_auth_properties(harness):
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

    assert "broker.id=0" in harness.charm.kafka_config.auth_properties
    assert (
        f"zookeeper.connect={harness.charm.kafka_config.zookeeper_config['connect']}"
        in harness.charm.kafka_config.auth_properties
    )


def test_super_users(harness):
    """Checks super-users property is updated for new admin clients."""
    assert len(harness.charm.kafka_config.super_users.split(";")) == 1

    client_relation_id = harness.add_relation("kafka-client", "app")
    harness.update_relation_data(client_relation_id, "app", {"extra-user-roles": "admin,producer"})
    client_relation_id = harness.add_relation("kafka-client", "appii")
    harness.update_relation_data(
        client_relation_id, "appii", {"extra-user-roles": "admin,consumer"}
    )

    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)

    harness.update_relation_data(
        peer_relation_id, harness.charm.app.name, {"relation-1": "mellon"}
    )
    assert len(harness.charm.kafka_config.super_users.split(";")) == 2

    harness.update_relation_data(
        peer_relation_id, harness.charm.app.name, {"relation-2": "mellon"}
    )

    harness.update_relation_data(client_relation_id, "appii", {"extra-user-roles": "consumer"})
    assert len(harness.charm.kafka_config.super_users.split(";")) == 2
