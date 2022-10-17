#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path
from unittest.mock import PropertyMock, patch

import pytest
import yaml
from ops.model import BlockedStatus, WaitingStatus
from ops.testing import Harness
from tenacity.wait import wait_none

from charm import KafkaCharm
from literals import CHARM_KEY, PEER, ZK

logger = logging.getLogger(__name__)

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


def test_install_sets_opts(harness):
    with patch("charms.kafka.v0.kafka_snap.KafkaSnap.install"), patch(
        "config.KafkaConfig.set_kafka_opts"
    ) as patched_opts:
        harness.charm.on.install.emit()

        patched_opts.assert_called_once()


def test_install_waits_until_zookeeper_relation(harness):
    with patch("charms.kafka.v0.kafka_snap.KafkaSnap.install"), patch(
        "config.KafkaConfig.set_kafka_opts"
    ):
        harness.charm.on.install.emit()
        assert isinstance(harness.charm.unit.status, WaitingStatus)


def test_install_blocks_snap_install_failure(harness):
    with patch("charms.kafka.v0.kafka_snap.KafkaSnap.install", return_value=False), patch(
        "config.KafkaConfig.set_kafka_opts"
    ):
        harness.charm.on.install.emit()
        assert isinstance(harness.charm.unit.status, BlockedStatus)


def test_leader_elected_sets_passwords(harness):
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")
    harness.set_leader(True)

    assert harness.charm.app_peer_data.get("sync_password", None)


def test_zookeeper_joined_sets_chroot(harness):
    harness.add_relation(PEER, CHARM_KEY)
    harness.set_leader(True)
    zk_rel_id = harness.add_relation(ZK, ZK)
    harness.add_relation_unit(zk_rel_id, f"zookeeper/0")

    assert CHARM_KEY in harness.charm.model.relations[ZK][0].data[harness.charm.app].get(
        "chroot", ""
    )


def test_zookeeper_broken_stops_service(harness):
    harness.add_relation(PEER, CHARM_KEY)
    zk_rel_id = harness.add_relation(ZK, ZK)

    with patch("charms.kafka.v0.kafka_snap.KafkaSnap.stop_snap_service") as patched:
        harness.remove_relation(zk_rel_id)

        patched.assert_called_once()
        assert isinstance(harness.charm.unit.status, BlockedStatus)


def test_start_defers_without_zookeeper(harness):
    with patch("ops.framework.EventBase.defer") as patched:
        harness.charm.on.start.emit()

        patched.assert_called_once()


def test_start_sets_necessary_config(harness):
    harness.add_relation(PEER, CHARM_KEY)
    zk_rel_id = harness.add_relation(ZK, ZK)
    harness.add_relation_unit(zk_rel_id, f"zookeeper/0")
    harness.update_relation_data(
        zk_rel_id,
        ZK,
        {
            "username": "relation-1",
            "password": "mellon",
            "endpoints": "123.123.123",
            "chroot": "/kafka",
            "uris": "123.123.123/kafka",
            "tls": "disabled",
        },
    )

    with patch("config.KafkaConfig.set_jaas_config") as patched_jaas, patch(
        "config.KafkaConfig.set_server_properties"
    ) as patched_properties:
        harness.charm.on.start.emit()
        patched_jaas.assert_called_once()
        patched_properties.assert_called_once()


def test_start_sets_auth_and_broker_creds_on_leader(harness):
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    zk_rel_id = harness.add_relation(ZK, ZK)
    harness.add_relation_unit(zk_rel_id, f"zookeeper/0")
    harness.update_relation_data(
        zk_rel_id,
        ZK,
        {
            "username": "relation-1",
            "password": "mellon",
            "endpoints": "123.123.123",
            "chroot": "/kafka",
            "uris": "123.123.123/kafka",
            "tls": "disabled",
        },
    )
    harness.update_relation_data(peer_rel_id, CHARM_KEY, {"sync-password": "mellon"})

    with patch("auth.KafkaAuth.add_user") as patched, patch(
        "config.KafkaConfig.set_jaas_config"
    ), patch("config.KafkaConfig.set_server_properties"), patch(
        "charm.broker_active"
    ) as patched_active:
        patched_active.retry.wait = wait_none
        harness.charm.on.start.emit()
        patched.assert_not_called()

        harness.set_leader(True)
        harness.charm.on.start.emit()
        patched.assert_called_once()


def test_start_does_not_start_if_not_ready(harness):
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    zk_rel_id = harness.add_relation(ZK, ZK)
    harness.add_relation_unit(zk_rel_id, f"zookeeper/0")
    harness.update_relation_data(
        zk_rel_id,
        ZK,
        {
            "username": "relation-1",
            "password": "mellon",
            "endpoints": "123.123.123",
            "chroot": "/kafka",
            "uris": "123.123.123/kafka",
            "tls": "disabled",
        },
    )
    harness.update_relation_data(peer_rel_id, CHARM_KEY, {"sync-password": "mellon"})

    with patch("auth.KafkaAuth.add_user"), patch("config.KafkaConfig.set_jaas_config"), patch(
        "config.KafkaConfig.set_server_properties"
    ), patch("charm.KafkaCharm.ready_to_start", new_callable=PropertyMock) as patched_start, patch(
        "charms.kafka.v0.kafka_snap.KafkaSnap.start_snap_service"
    ) as patched_service:
        patched_start.return_value = False
        harness.charm.on.start.emit()

        patched_service.assert_not_called()


def test_start_does_not_start_if_not_same_tls_as_zk(harness):
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    zk_rel_id = harness.add_relation(ZK, ZK)
    harness.add_relation_unit(zk_rel_id, f"zookeeper/0")
    harness.update_relation_data(
        zk_rel_id,
        ZK,
        {
            "username": "relation-1",
            "password": "mellon",
            "endpoints": "123.123.123",
            "chroot": "/kafka",
            "uris": "123.123.123/kafka",
            "tls": "enabled",
        },
    )
    harness.update_relation_data(peer_rel_id, CHARM_KEY, {"sync-password": "mellon"})

    with patch("auth.KafkaAuth.add_user"), patch("config.KafkaConfig.set_jaas_config"), patch(
        "config.KafkaConfig.set_server_properties"
    ), patch("charms.kafka.v0.kafka_snap.KafkaSnap.start_snap_service") as patched_service:
        harness.charm.on.start.emit()

        patched_service.assert_not_called()
        assert isinstance(harness.charm.unit.status, BlockedStatus)


def test_start_does_not_start_if_leader_has_not_set_creds(harness):
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    zk_rel_id = harness.add_relation(ZK, ZK)
    harness.add_relation_unit(zk_rel_id, f"zookeeper/0")
    harness.update_relation_data(
        zk_rel_id,
        ZK,
        {
            "username": "relation-1",
            "password": "mellon",
            "endpoints": "123.123.123",
            "chroot": "/kafka",
            "uris": "123.123.123/kafka",
            "tls": "enabled",
        },
    )
    harness.update_relation_data(peer_rel_id, CHARM_KEY, {"sync-password": "mellon"})

    with patch("config.KafkaConfig.set_jaas_config"), patch(
        "config.KafkaConfig.set_server_properties"
    ), patch("charms.kafka.v0.kafka_snap.KafkaSnap.start_snap_service") as patched_service:
        harness.charm.on.start.emit()

        patched_service.assert_not_called()
        assert isinstance(harness.charm.unit.status, BlockedStatus)


def test_start_blocks_if_service_failed_silently(harness):
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    zk_rel_id = harness.add_relation(ZK, ZK)
    harness.add_relation_unit(zk_rel_id, f"zookeeper/0")
    harness.update_relation_data(
        zk_rel_id,
        ZK,
        {
            "username": "relation-1",
            "password": "mellon",
            "endpoints": "123.123.123",
            "chroot": "/kafka",
            "uris": "123.123.123/kafka",
            "tls": "disabled",
        },
    )
    harness.update_relation_data(peer_rel_id, CHARM_KEY, {"sync-password": "mellon"})
    harness.set_leader(True)

    with patch("auth.KafkaAuth.add_user"), patch("config.KafkaConfig.set_jaas_config"), patch(
        "config.KafkaConfig.set_server_properties"
    ), patch("charms.kafka.v0.kafka_snap.KafkaSnap.start_snap_service") as patched_service, patch(
        "charm.broker_active", return_value=False
    ) as patched_active:
        patched_active.retry.wait = wait_none
        harness.charm.on.start.emit()

        patched_service.assert_called_once()
        assert isinstance(harness.charm.unit.status, BlockedStatus)


def test_config_changed_updates_properties(harness):
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")

    with patch(
        "config.KafkaConfig.server_properties", new_callable=PropertyMock
    ) as patched_properties, patch(
        "charm.KafkaCharm.ready_to_start", new_callable=PropertyMock
    ) as patched_ready, patch(
        "charm.safe_get_file", return_value=["gandalf=grey"]
    ), patch(
        "config.KafkaConfig.set_server_properties"
    ) as set_props:
        patched_properties.return_value = ["gandalf=white"]
        patched_ready.return_value = True

        harness.charm.on.config_changed.emit()
        set_props.assert_called_once()
