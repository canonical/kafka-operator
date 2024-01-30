#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import socket
from pathlib import Path

import pytest
import yaml
from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness

from charm import KafkaCharm
from literals import CHARM_KEY, CONTAINER, PEER, SUBSTRATE, ZK

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
        }
    )
    harness.begin()

    # Relate to ZK with tls enabled
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


def test_blocked_if_trusted_certificate_added_before_tls_relation(harness: Harness):
    # Create peer relation
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_relation_id, f"{CHARM_KEY}/1")
    harness.update_relation_data(
        peer_relation_id, f"{CHARM_KEY}/0", {"private-address": "treebeard"}
    )

    harness.set_leader(True)
    harness.add_relation("trusted-certificate", "tls-one")

    assert isinstance(harness.charm.app.status, BlockedStatus)


def test_mtls_flag_added(harness: Harness):
    # Create peer relation
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_relation_id, f"{CHARM_KEY}/1")
    harness.update_relation_data(
        peer_relation_id, f"{CHARM_KEY}/0", {"private-address": "treebeard"}
    )
    harness.update_relation_data(peer_relation_id, CHARM_KEY, {"tls": "enabled"})

    harness.set_leader(True)
    harness.add_relation("trusted-certificate", "tls-one")

    peer_relation_data = harness.get_relation_data(peer_relation_id, CHARM_KEY)
    assert peer_relation_data.get("mtls", "disabled") == "enabled"
    assert isinstance(harness.charm.app.status, ActiveStatus)


def test_extra_sans_config(harness: Harness):
    # Create peer relation
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_relation_id, f"{CHARM_KEY}/0")
    harness.update_relation_data(
        peer_relation_id, f"{CHARM_KEY}/0", {"private-address": "treebeard"}
    )

    harness.update_config({"certificate_extra_sans": ""})
    assert harness.charm.tls._extra_sans == []

    harness.update_config({"certificate_extra_sans": "worker{unit}.com"})
    assert harness.charm.tls._extra_sans == ["worker0.com"]

    harness.update_config({"certificate_extra_sans": "worker{unit}.com,{unit}.example"})
    assert harness.charm.tls._extra_sans == ["worker0.com", "0.example"]


def test_sans(harness: Harness):
    # Create peer relation
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_relation_id, f"{CHARM_KEY}/0")
    harness.update_relation_data(
        peer_relation_id, f"{CHARM_KEY}/0", {"private-address": "treebeard"}
    )
    harness.update_config({"certificate_extra_sans": "worker{unit}.com"})

    sock_dns = socket.getfqdn()
    assert harness.charm.tls._sans == {
        "sans_ip": ["treebeard" if SUBSTRATE == "vm" else "kafka-k8s-0.kafka-k8s-endpoints"],
        "sans_dns": [f"{CHARM_KEY}/0", sock_dns, "worker0.com"],
    }
