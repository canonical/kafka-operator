#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
import yaml
from charms.data_platform_libs.v0.upgrade import ClusterNotReadyError, DependencyModel
from kazoo.client import KazooClient
from ops.testing import Harness

from charm import KafkaCharm
from literals import CHARM_KEY, DEPENDENCIES, PEER, ZK
from snap import KafkaSnap
from upgrade import KafkaDependencyModel, KafkaUpgrade

logger = logging.getLogger(__name__)


CONFIG = str(yaml.safe_load(Path("./config.yaml").read_text()))
ACTIONS = str(yaml.safe_load(Path("./actions.yaml").read_text()))
METADATA = str(yaml.safe_load(Path("./metadata.yaml").read_text()))


@pytest.fixture
def harness(zk_data):
    harness = Harness(KafkaCharm, meta=METADATA, config=CONFIG, actions=ACTIONS)
    harness.add_relation("restart", CHARM_KEY)
    harness.add_relation("upgrade", CHARM_KEY)
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    zk_rel_id = harness.add_relation(ZK, ZK)
    harness._update_config(
        {
            "log_retention_ms": "-1",
            "compression_type": "producer",
        }
    )
    harness.begin()
    with harness.hooks_disabled():
        harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")
        harness.update_relation_data(
            peer_rel_id, f"{CHARM_KEY}/0", {"private-address": "000.000.000"}
        )
        harness.update_relation_data(zk_rel_id, ZK, zk_data)

    return harness


def test_pre_upgrade_check_raises_not_stable(harness):
    with pytest.raises(ClusterNotReadyError):
        harness.charm.upgrade.pre_upgrade_check()


def test_pre_upgrade_check_succeeds(harness):
    with patch("charm.KafkaCharm.healthy", return_value=True):
        harness.charm.upgrade.pre_upgrade_check()


def test_build_upgrade_stack(harness):
    with harness.hooks_disabled():
        harness.add_relation_unit(harness.charm.peer_relation.id, f"{CHARM_KEY}/1")
        harness.update_relation_data(
            harness.charm.peer_relation.id, f"{CHARM_KEY}/1", {"private-address": "111.111.111"}
        )
        harness.add_relation_unit(harness.charm.peer_relation.id, f"{CHARM_KEY}/2")
        harness.update_relation_data(
            harness.charm.peer_relation.id, f"{CHARM_KEY}/2", {"private-address": "222.222.222"}
        )

    stack = harness.charm.upgrade.build_upgrade_stack()

    assert len(stack) == 3
    assert len(stack) == len(set(stack))


@pytest.mark.parametrize("upgrade_state", ("idle", "ready"))
@pytest.mark.parametrize("upgrade_stack", ([], [0]))
def test_run_password_rotation_while_upgrading(harness, upgrade_state, upgrade_stack):
    harness.charm.upgrade.peer_relation.data[harness.charm.unit].update({"state": upgrade_state})
    harness.charm.upgrade.upgrade_stack = upgrade_stack
    harness.set_leader(True)

    mock_event = MagicMock()
    mock_event.params = {"username": "admin"}

    with (
        patch("charm.KafkaCharm.healthy", new_callable=PropertyMock, return_value=True),
        patch("auth.KafkaAuth.add_user"),
    ):
        harness.charm._set_password_action(mock_event)

    if (not upgrade_stack) and (upgrade_state == "idle"):
        mock_event.set_results.assert_called()
    else:
        mock_event.fail.assert_called_with(
            f"Cannot set password while upgrading (upgrade_state: {upgrade_state}, "
            + f"upgrade_stack: {upgrade_stack})"
        )


def test_kafka_dependency_model():
    assert sorted(KafkaDependencyModel.__fields__.keys()) == sorted(DEPENDENCIES.keys())

    for value in DEPENDENCIES.values():
        assert DependencyModel(**value)


def test_upgrade_granted_sets_failed_if_zookeeper_dependency_check_fails(harness):
    with (
        patch.object(KazooClient, "start"),
        patch("utils.ZooKeeperManager.get_leader", return_value="000.000.000"),
        # NOTE: Dependency requires >3
        patch("utils.ZooKeeperManager.get_version", return_value="1.2.3"),
    ):
        mock_event = MagicMock()
        harness.charm.upgrade._on_upgrade_granted(mock_event)

    assert harness.charm.upgrade.state == "failed"


def test_upgrade_granted_sets_failed_if_failed_snap(harness):
    with (
        patch(
            "upgrade.KafkaUpgrade.zookeeper_current_version",
            new_callable=PropertyMock,
            return_value="3.6",
        ),
        patch.object(KafkaSnap, "stop_snap_service") as patched_stop,
        patch.object(KafkaSnap, "install", return_value=False),
    ):
        mock_event = MagicMock()
        harness.charm.upgrade._on_upgrade_granted(mock_event)

    patched_stop.assert_called_once()
    assert harness.charm.upgrade.state == "failed"


def test_upgrade_granted_sets_failed_if_failed_upgrade_check(harness):
    with (
        patch(
            "upgrade.KafkaUpgrade.zookeeper_current_version",
            new_callable=PropertyMock,
            return_value="3.6",
        ),
        patch.object(KafkaSnap, "stop_snap_service"),
        patch.object(KafkaSnap, "restart_snap_service") as patched_restart,
        patch.object(KafkaSnap, "install", return_value=True),
        patch("charm.KafkaCharm.healthy", new_callable=PropertyMock, return_value=False),
    ):
        mock_event = MagicMock()
        harness.charm.upgrade._on_upgrade_granted(mock_event)

    patched_restart.assert_called_once()
    assert harness.charm.upgrade.state == "failed"


def test_upgrade_granted_succeeds(harness):
    with (
        patch(
            "upgrade.KafkaUpgrade.zookeeper_current_version",
            new_callable=PropertyMock,
            return_value="3.6",
        ),
        patch.object(KafkaSnap, "stop_snap_service"),
        patch.object(KafkaSnap, "restart_snap_service"),
        patch.object(KafkaSnap, "install", return_value=True),
        patch("charm.KafkaCharm.healthy", new_callable=PropertyMock, return_value=True),
    ):
        mock_event = MagicMock()
        harness.charm.upgrade._on_upgrade_granted(mock_event)

    assert harness.charm.upgrade.state == "completed"


def test_upgrade_granted_recurses_upgrade_changed_on_leader(harness):
    with harness.hooks_disabled():
        harness.set_leader(True)

    with (
        patch(
            "upgrade.KafkaUpgrade.zookeeper_current_version",
            new_callable=PropertyMock,
            return_value="3.6",
        ),
        patch.object(KafkaSnap, "stop_snap_service"),
        patch.object(KafkaSnap, "restart_snap_service"),
        patch.object(KafkaSnap, "install", return_value=True),
        patch("charm.KafkaCharm.healthy", new_callable=PropertyMock, return_value=True),
        patch.object(KafkaUpgrade, "on_upgrade_changed") as patched_upgrade,
    ):
        mock_event = MagicMock()
        harness.charm.upgrade._on_upgrade_granted(mock_event)

    patched_upgrade.assert_called_once()
