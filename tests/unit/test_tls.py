#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from pathlib import Path

import pytest
import yaml
from ops.model import ActiveStatus, BlockedStatus
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


def test_blocked_if_trusted_certificates_added_before_tls_relation(harness: Harness):
    # Create peer relation
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_relation_id, "kafka/1")
    harness.update_relation_data(peer_relation_id, "kafka/0", {"private-address": "treebeard"})

    harness.set_leader(True)
    harness.add_relation("trusted-certificates", "tls-one")

    assert isinstance(harness.charm.app.status, BlockedStatus)


def test_mtls_flag_added(harness: Harness):
    # Create peer relation
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_relation_id, "kafka/1")
    harness.update_relation_data(peer_relation_id, "kafka/0", {"private-address": "treebeard"})
    harness.update_relation_data(peer_relation_id, "kafka", {"tls": "enabled"})

    harness.set_leader(True)
    harness.add_relation("trusted-certificates", "tls-one")

    peer_relation_data = harness.get_relation_data(peer_relation_id, "kafka")
    assert peer_relation_data.get("mtls", "disabled") == "enabled"
    assert isinstance(harness.charm.app.status, ActiveStatus)
