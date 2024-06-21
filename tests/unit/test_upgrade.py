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
from events.upgrade import KafkaDependencyModel
from literals import CHARM_KEY, CONTAINER, DEPENDENCIES, PEER, SUBSTRATE, ZK

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker

CONFIG = str(yaml.safe_load(Path("./config.yaml").read_text()))
ACTIONS = str(yaml.safe_load(Path("./actions.yaml").read_text()))
METADATA = str(yaml.safe_load(Path("./metadata.yaml").read_text()))


@pytest.fixture()
def upgrade_func() -> str:
    if SUBSTRATE == "k8s":
        return "_on_kafka_pebble_ready_upgrade"

    return "_on_upgrade_granted"


@pytest.fixture
def harness(zk_data):
    harness = Harness(KafkaCharm, meta=METADATA, config=CONFIG, actions=ACTIONS)
    harness.add_relation("restart", CHARM_KEY)
    harness.add_relation("upgrade", CHARM_KEY)

    if SUBSTRATE == "k8s":
        harness.set_can_connect(CONTAINER, True)

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


def test_pre_upgrade_check_raises_not_stable(harness: Harness[KafkaCharm]):
    with pytest.raises(ClusterNotReadyError):
        harness.charm.broker.upgrade.pre_upgrade_check()


def test_pre_upgrade_check_succeeds(harness: Harness[KafkaCharm]):
    with (
        patch("events.broker.BrokerOperator.healthy", return_value=True),
        patch("events.upgrade.KafkaUpgrade._set_rolling_update_partition"),
    ):
        harness.charm.broker.upgrade.pre_upgrade_check()


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="upgrade stack not used on K8s")
def test_build_upgrade_stack(harness: Harness[KafkaCharm]):
    with harness.hooks_disabled():
        harness.add_relation_unit(harness.charm.state.peer_relation.id, f"{CHARM_KEY}/1")
        harness.update_relation_data(
            harness.charm.state.peer_relation.id,
            f"{CHARM_KEY}/1",
            {"private-address": "111.111.111"},
        )
        harness.add_relation_unit(harness.charm.state.peer_relation.id, f"{CHARM_KEY}/2")
        harness.update_relation_data(
            harness.charm.state.peer_relation.id,
            f"{CHARM_KEY}/2",
            {"private-address": "222.222.222"},
        )

    stack = harness.charm.broker.upgrade.build_upgrade_stack()

    assert len(stack) == 3
    assert len(stack) == len(set(stack))


@pytest.mark.parametrize("upgrade_stack", ([], [0]))
def test_run_password_rotation_while_upgrading(harness: Harness[KafkaCharm], upgrade_stack):
    harness.charm.broker.upgrade.upgrade_stack = upgrade_stack
    harness.set_leader(True)

    mock_event = MagicMock()
    mock_event.params = {"username": "admin"}

    with (
        patch(
            "events.broker.BrokerOperator.healthy", new_callable=PropertyMock, return_value=True
        ),
        patch("managers.auth.AuthManager.add_user"),
    ):
        harness.charm.broker.password_action_events._set_password_action(mock_event)

    if not upgrade_stack:
        mock_event.set_results.assert_called()
    else:
        mock_event.fail.assert_called_with(
            f"Cannot set password while upgrading (upgrade_stack: {upgrade_stack})"
        )


def test_kafka_dependency_model():
    assert sorted(KafkaDependencyModel.__fields__.keys()) == sorted(DEPENDENCIES.keys())

    for value in DEPENDENCIES.values():
        assert DependencyModel(**value)


def test_upgrade_granted_sets_failed_if_zookeeper_dependency_check_fails(
    harness: Harness[KafkaCharm], upgrade_func: str
):
    with harness.hooks_disabled():
        harness.set_leader(True)

    with (
        patch.object(KazooClient, "start"),
        patch(
            "core.models.ZooKeeperManager.get_leader",
            new_callable=PropertyMock,
            return_value="000.000.000",
        ),
        # NOTE: Dependency requires >3
        patch(
            "core.models.ZooKeeper.zookeeper_version",
            new_callable=PropertyMock,
            return_value="1.2.3",
        ),
        patch(
            "core.cluster.ClusterState.ready_to_start",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch(
            "events.upgrade.KafkaUpgrade.idle",
            new_callable=PropertyMock,
            return_value=False,
        ),
    ):
        mock_event = MagicMock()
        getattr(harness.charm.broker.upgrade, upgrade_func)(mock_event)

    assert harness.charm.broker.upgrade.state == "failed"


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="Upgrade granted not used on K8s charms")
def test_upgrade_granted_sets_failed_if_failed_snap(harness: Harness[KafkaCharm]):
    with (
        patch(
            "events.upgrade.KafkaUpgrade.zookeeper_current_version",
            new_callable=PropertyMock,
            return_value="3.6",
        ),
        patch("workload.KafkaWorkload.stop") as patched_stop,
        patch("workload.KafkaWorkload.install", return_value=False),
    ):
        mock_event = MagicMock()
        harness.charm.broker.upgrade._on_upgrade_granted(mock_event)

    patched_stop.assert_called_once()
    assert harness.charm.broker.upgrade.state == "failed"


def test_upgrade_sets_failed_if_failed_upgrade_check(
    harness: Harness[KafkaCharm], upgrade_func: str
):
    with (
        patch(
            "core.models.ZooKeeper.zookeeper_version",
            new_callable=PropertyMock,
            return_value="3.6.2",
        ),
        patch("time.sleep"),
        patch("managers.config.ConfigManager.set_environment"),
        patch("managers.config.ConfigManager.set_server_properties"),
        patch("managers.config.ConfigManager.set_zk_jaas_config"),
        patch("managers.config.ConfigManager.set_client_properties"),
        patch("workload.KafkaWorkload.restart") as patched_restart,
        patch("workload.KafkaWorkload.start") as patched_start,
        patch("workload.KafkaWorkload.stop"),
        patch("workload.KafkaWorkload.install"),
        patch(
            "events.broker.BrokerOperator.healthy", new_callable=PropertyMock, return_value=False
        ),
        patch(
            "core.cluster.ClusterState.ready_to_start",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch(
            "events.upgrade.KafkaUpgrade.idle",
            new_callable=PropertyMock,
            return_value=False,
        ),
    ):
        mock_event = MagicMock()
        getattr(harness.charm.broker.upgrade, upgrade_func)(mock_event)

    assert patched_restart.call_count or patched_start.call_count
    assert harness.charm.broker.upgrade.state == "failed"


def test_upgrade_succeeds(harness: Harness[KafkaCharm], upgrade_func: str):
    with (
        patch(
            "core.models.ZooKeeper.zookeeper_version",
            new_callable=PropertyMock,
            return_value="3.6.2",
        ),
        patch("time.sleep"),
        patch("managers.config.ConfigManager.set_environment"),
        patch("managers.config.ConfigManager.set_server_properties"),
        patch("managers.config.ConfigManager.set_zk_jaas_config"),
        patch("managers.config.ConfigManager.set_client_properties"),
        patch("workload.KafkaWorkload.restart") as patched_restart,
        patch("workload.KafkaWorkload.start") as patched_start,
        patch("workload.KafkaWorkload.stop"),
        patch("workload.KafkaWorkload.install"),
        patch("workload.KafkaWorkload.active", new_callable=PropertyMock, return_value=True),
        patch(
            "events.broker.BrokerOperator.healthy", new_callable=PropertyMock, return_value=True
        ),
        patch(
            "core.cluster.ClusterState.ready_to_start",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch(
            "events.upgrade.KafkaUpgrade.idle",
            new_callable=PropertyMock,
            return_value=False,
        ),
        patch(
            "core.models.ZooKeeper.broker_active",
            return_value=True,
        ),
    ):
        mock_event = MagicMock()
        getattr(harness.charm.broker.upgrade, upgrade_func)(mock_event)

    assert patched_restart.call_count or patched_start.call_count
    assert harness.charm.broker.upgrade.state == "completed"


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="Upgrade granted not used on K8s charms")
def test_upgrade_granted_recurses_upgrade_changed_on_leader(harness: Harness[KafkaCharm]):
    with harness.hooks_disabled():
        harness.set_leader(True)

    with (
        patch(
            "events.upgrade.KafkaUpgrade.zookeeper_current_version",
            new_callable=PropertyMock,
            return_value="3.6",
        ),
        patch("time.sleep"),
        patch("workload.KafkaWorkload.stop"),
        patch("workload.KafkaWorkload.restart"),
        patch("workload.KafkaWorkload.install", return_value=True),
        patch(
            "events.broker.BrokerOperator.healthy", new_callable=PropertyMock, return_value=True
        ),
        patch("events.upgrade.KafkaUpgrade.on_upgrade_changed") as patched_upgrade,
    ):
        mock_event = MagicMock()
        harness.charm.broker.upgrade._on_upgrade_granted(mock_event)

    patched_upgrade.assert_called_once()
