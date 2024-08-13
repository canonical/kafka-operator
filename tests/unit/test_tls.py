#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import socket
from pathlib import Path
from unittest.mock import PropertyMock, patch

import pytest
import yaml
from ops.model import ActiveStatus
from ops.testing import Harness

from charm import KafkaCharm
from literals import CHARM_KEY, CONTAINER, PEER, SUBSTRATE, ZK

pytestmark = pytest.mark.broker

CONFIG = str(yaml.safe_load(Path("./config.yaml").read_text()))
ACTIONS = str(yaml.safe_load(Path("./actions.yaml").read_text()))
METADATA = str(yaml.safe_load(Path("./metadata.yaml").read_text()))


@pytest.fixture
def harness():
    harness = Harness(KafkaCharm, meta=METADATA, actions=ACTIONS, config=CONFIG)

    if SUBSTRATE == "k8s":
        harness.set_can_connect(CONTAINER, True)

    harness.add_relation("restart", CHARM_KEY)
    harness._update_config(
        {
            "log_retention_ms": "-1",
            "compression_type": "producer",
            "expose-external": "none",
        }
    )
    harness.begin()

    # Relate to ZK with tls enabled
    zk_relation_id = harness.add_relation(ZK, CHARM_KEY)
    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "database": "/kafka",
            "chroot": "/kafka",
            "username": "moria",
            "password": "mellon",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181/kafka,2.2.2.2:2181/kafka",
            "tls": "enabled",
        },
    )

    # Simulate data-integrator relation
    client_relation_id = harness.add_relation("kafka-client", "app")
    harness.update_relation_data(client_relation_id, "app", {"extra-user-roles": "admin,producer"})
    client_relation_id = harness.add_relation("kafka-client", "appii")
    harness.update_relation_data(
        client_relation_id, "appii", {"extra-user-roles": "admin,consumer"}
    )

    return harness


def test_mtls_not_enabled_if_trusted_certificate_added_before_tls_relation(
    harness: Harness[KafkaCharm],
):
    # Create peer relation
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_relation_id, f"{CHARM_KEY}/1")
    harness.update_relation_data(
        peer_relation_id, f"{CHARM_KEY}/0", {"private-address": "treebeard"}
    )

    harness.set_leader(True)
    harness.add_relation("trusted-certificate", "tls-one")

    assert not harness.charm.state.cluster.mtls_enabled


def test_mtls_flag_added(harness: Harness[KafkaCharm]):
    # Create peer relation
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_relation_id, f"{CHARM_KEY}/1")
    harness.update_relation_data(
        peer_relation_id, f"{CHARM_KEY}/0", {"private-address": "treebeard"}
    )
    harness.update_relation_data(peer_relation_id, CHARM_KEY, {"tls": "enabled"})

    harness.set_leader(True)
    harness.add_relation("trusted-certificate", "tls-one")

    assert harness.charm.state.cluster.mtls_enabled
    assert isinstance(harness.charm.app.status, ActiveStatus)


def test_extra_sans_config(harness: Harness[KafkaCharm]):
    # Create peer relation
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_relation_id, f"{CHARM_KEY}/0")
    harness.update_relation_data(
        peer_relation_id, f"{CHARM_KEY}/0", {"private-address": "treebeard"}
    )

    manager = harness.charm.broker.tls_manager

    harness._update_config({"certificate_extra_sans": ""})
    manager.config = harness.charm.config
    assert manager._build_extra_sans() == []

    harness._update_config({"certificate_extra_sans": "worker{unit}.com"})
    manager.config = harness.charm.config
    assert "worker0.com" in "".join(manager._build_extra_sans())

    harness._update_config({"certificate_extra_sans": "worker{unit}.com,{unit}.example"})
    manager.config = harness.charm.config
    assert "worker0.com" in "".join(manager._build_extra_sans())
    assert "0.example" in "".join(manager._build_extra_sans())


def test_sans(harness: Harness[KafkaCharm], patched_node_ip):
    # Create peer relation
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_relation_id, f"{CHARM_KEY}/0")
    harness.update_relation_data(
        peer_relation_id, f"{CHARM_KEY}/0", {"private-address": "treebeard"}
    )

    manager = harness.charm.broker.tls_manager
    harness.update_config({"certificate_extra_sans": "worker{unit}.com"})
    manager.config = harness.charm.config

    sock_dns = socket.getfqdn()
    if SUBSTRATE == "vm":
        assert manager.build_sans() == {
            "sans_ip": ["treebeard"],
            "sans_dns": [f"{CHARM_KEY}/0", sock_dns, "worker0.com"],
        }
    elif SUBSTRATE == "k8s":
        # NOTE previous k8s sans_ip like kafka-k8s-0.kafka-k8s-endpoints or binding pod address
        with (
            patch("ops.model.Model.get_binding"),
            patch(
                "core.models.KafkaBroker.node_ip",
                new_callable=PropertyMock,
                return_value="palantir",
            ),
        ):
            assert sorted(manager.build_sans()["sans_dns"]) == sorted(
                [
                    "kafka-k8s-0",
                    "kafka-k8s-0.kafka-k8s-endpoints",
                    sock_dns,
                    "worker0.com",
                ]
            )
            assert "palantir" in "".join(manager.build_sans()["sans_ip"])
