#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from ops.charm import CharmBase
from ops.testing import Harness

from config import KafkaConfig

METADATA = """
    name: kafka
    peers:
        cluster:
            interface: cluster
    requires:
        zookeeper:
            interface: zookeeper
    provides:
        kafka-client:
            interface: client
"""


class DummyKafkaCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.kafka_config = KafkaConfig(self)


@pytest.fixture(scope="function")
def harness():
    harness = Harness(DummyKafkaCharm, meta=METADATA)
    harness.begin_with_initial_hooks()
    return harness


@pytest.fixture(scope="function")
def zk_relation_id(harness):
    relation_id = harness.add_relation("zookeeper", "kafka")
    return relation_id


def test_zookeeper_config_succeeds_fails_config(zk_relation_id, harness):
    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "chroot": "/kafka",
            "username": "moria",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181,2.2.2.2:2181/kafka",
        },
    )
    assert harness.charm.kafka_config.zookeeper_config == {}
    assert not harness.charm.kafka_config.zookeeper_connected


def test_zookeeper_config_succeeds_valid_config(zk_relation_id, harness):
    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "chroot": "/kafka",
            "username": "moria",
            "password": "mellon",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181/kafka,2.2.2.2:2181/kafka",
        },
    )
    assert "connect" in harness.charm.kafka_config.zookeeper_config
    assert (
        harness.charm.kafka_config.zookeeper_config["connect"] == "1.1.1.1:2181,2.2.2.2:2181/kafka"
    )
    assert harness.charm.kafka_config.zookeeper_connected


def test_extra_args(harness):
    args = "".join(harness.charm.kafka_config.extra_args)
    assert "-Djava.security.auth.login.config" in args


def test_bootstrap_server(harness):
    peer_relation_id = harness.charm.model.get_relation("cluster").id
    harness.add_relation_unit(peer_relation_id, "kafka/1")
    harness.update_relation_data(peer_relation_id, "kafka/0", {"private-address": "treebeard"})
    harness.update_relation_data(peer_relation_id, "kafka/1", {"private-address": "shelob"})

    assert len(harness.charm.kafka_config.bootstrap_server) == 2
    for server in harness.charm.kafka_config.bootstrap_server:
        assert "9092" in server


def test_default_replication_properties_less_than_three(harness):
    assert "num.partitions=1" in harness.charm.kafka_config.default_replication_properties
    assert (
        "default.replication.factor=1" in harness.charm.kafka_config.default_replication_properties
    )
    assert "min.insync.replicas=1" in harness.charm.kafka_config.default_replication_properties


def test_default_replication_properties_more_than_three(harness):
    peer_relation_id = harness.charm.model.get_relation("cluster").id
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


def test_auth_properties(zk_relation_id, harness):
    peer_relation_id = harness.charm.model.get_relation("cluster").id
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
        },
    )

    assert "broker.id=0" in harness.charm.kafka_config.auth_properties
    assert (
        f"zookeeper.connect={harness.charm.kafka_config.zookeeper_config['connect']}"
        in harness.charm.kafka_config.auth_properties
    )
    assert (
        'listener.name.sasl_plaintext.scram-sha-512.sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="sync" password="mellon";'
        in harness.charm.kafka_config.auth_properties
    )


def test_super_users(harness):
    assert len(harness.charm.kafka_config.super_users.split(";")) == 1

    client_relation_id = harness.add_relation("kafka-client", "app")
    harness.update_relation_data(client_relation_id, "app", {"extra-user-roles": "admin,producer"})
    client_relation_id = harness.add_relation("kafka-client", "appii")
    harness.update_relation_data(
        client_relation_id, "appii", {"extra-user-roles": "admin,consumer"}
    )

    peer_relation_id = harness.charm.model.get_relation("cluster").id

    harness.update_relation_data(
        peer_relation_id, harness.charm.app.name, {"relation-1": "mellon"}
    )
    assert len(harness.charm.kafka_config.super_users.split(";")) == 2

    harness.update_relation_data(
        peer_relation_id, harness.charm.app.name, {"relation-2": "mellon"}
    )

    harness.update_relation_data(
        client_relation_id, "appii", {"extra-user-roles": "consumer"}
    )
    assert len(harness.charm.kafka_config.super_users.split(";")) == 2
