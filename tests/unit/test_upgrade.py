#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
import json
import logging
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
import yaml
from charms.data_platform_libs.v0.upgrade import ClusterNotReadyError, DependencyModel
from kazoo.client import KazooClient
from ops.testing import ActionFailed, Harness
from scenario import Container, Context, PeerRelation, State

from charm import KafkaCharm
from events.upgrade import KafkaDependencyModel
from literals import CHARM_KEY, CONTAINER, DEPENDENCIES, PEER, SUBSTRATE, ZK

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker


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


@pytest.fixture()
def upgrade_func() -> str:
    if SUBSTRATE == "k8s":
        return "_on_kafka_pebble_ready_upgrade"

    return "_on_upgrade_granted"


@pytest.fixture
def harness(zk_data):
    harness = Harness(KafkaCharm, meta=str(METADATA), config=str(CONFIG), actions=str(ACTIONS))
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


def test_pre_upgrade_check_raises_not_stable(ctx: Context, base_state: State) -> None:
    # Given
    state_in = base_state

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)

        with pytest.raises(ClusterNotReadyError):
            charm.broker.upgrade.pre_upgrade_check()


def test_pre_upgrade_check_succeeds(ctx: Context, base_state: State) -> None:
    # Given
    state_in = base_state

    # When
    with (
        patch("events.broker.BrokerOperator.healthy", return_value=True),
        patch("events.upgrade.KafkaUpgrade._set_rolling_update_partition"),
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)

        # Then
        charm.broker.upgrade.pre_upgrade_check()


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="upgrade stack not used on K8s")
def test_build_upgrade_stack(ctx: Context, base_state: State) -> None:
    # Given
    cluster_peer = PeerRelation(
        PEER,
        PEER,
        local_unit_data={"private-address": "000.000.000"},
        peers_data={1: {"private-address": "111.111.111"}, 2: {"private-address": "222.222.222"}},
    )
    state_in = dataclasses.replace(base_state, relations=[cluster_peer])

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)
        stack = charm.broker.upgrade.build_upgrade_stack()

    # Then
    assert len(stack) == 3
    assert len(stack) == len(set(stack))


@pytest.mark.parametrize("upgrade_stack", ([], [0]))
def test_run_password_rotation_while_upgrading(
    ctx: Context, base_state: State, upgrade_stack
) -> None:
    # Given
    state_in = base_state

    # When
    with (
        patch(
            "events.broker.BrokerOperator.healthy", new_callable=PropertyMock, return_value=True
        ),
        patch("managers.auth.AuthManager.add_user"),
        patch(
            "charms.data_platform_libs.v0.upgrade.DataUpgrade.upgrade_stack",
            new_callable=PropertyMock,
            return_value=upgrade_stack,
        ),
    ):
        if not upgrade_stack:
            ctx.run(ctx.on.action("set-password", params={"username": "admin"}), state_in)

        else:
            with pytest.raises(ActionFailed, match="Cannot set password while upgrading"):
                ctx.run(ctx.on.action("set-password", params={"username": "admin"}), state_in)


def test_kafka_dependency_model():
    assert sorted(KafkaDependencyModel.__fields__.keys()) == sorted(DEPENDENCIES.keys())

    for value in DEPENDENCIES.values():
        assert DependencyModel(**value)


def test_upgrade_granted_sets_failed_if_zookeeper_dependency_check_fails(
    ctx: Context, base_state: State, upgrade_func: str
):
    # Given
    state_in = base_state

    # When
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
        patch(
            "events.upgrade.KafkaUpgrade.set_unit_failed",
        ) as patch_set_failed,
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)
        mock_event = MagicMock()
        getattr(charm.broker.upgrade, upgrade_func)(mock_event)

    # Then
    assert patch_set_failed.call_count


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="Upgrade granted not used on K8s charms")
def test_upgrade_granted_sets_failed_if_failed_snap(ctx: Context, base_state: State) -> None:
    # Given
    state_in = base_state

    # Then
    with (
        patch(
            "events.upgrade.KafkaUpgrade.zookeeper_current_version",
            new_callable=PropertyMock,
            return_value="3.6.2",
        ),
        patch("workload.KafkaWorkload.stop") as patched_stop,
        patch("workload.BalancerWorkload.stop"),
        patch("workload.KafkaWorkload.install", return_value=False),
        patch(
            "events.upgrade.KafkaUpgrade.set_unit_failed",
        ) as patch_set_failed,
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)
        mock_event = MagicMock()
        charm.broker.upgrade._on_upgrade_granted(mock_event)

    # Then
    patched_stop.assert_called_once()
    assert patch_set_failed.call_count


def test_upgrade_sets_failed_if_failed_upgrade_check(
    ctx: Context, base_state: State, upgrade_func: str
) -> None:
    # Given
    state_in = base_state

    # When
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
        patch("workload.BalancerWorkload.stop"),
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
        patch(
            "events.upgrade.KafkaUpgrade.set_unit_failed",
        ) as patch_set_failed,
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)
        mock_event = MagicMock()
        getattr(charm.broker.upgrade, upgrade_func)(mock_event)

    # Then
    assert patched_restart.call_count or patched_start.call_count
    assert patch_set_failed.call_count


def test_upgrade_succeeds(ctx: Context, base_state: State, upgrade_func: str) -> None:
    # Given
    state_in = base_state

    # When
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
        patch("workload.BalancerWorkload.stop"),
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
        patch(
            "events.upgrade.KafkaUpgrade.set_unit_completed",
        ) as patch_set_completed,
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)
        mock_event = MagicMock()
        getattr(charm.broker.upgrade, upgrade_func)(mock_event)

    assert patched_restart.call_count or patched_start.call_count
    assert patch_set_completed.call_count


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="Upgrade granted not used on K8s charms")
def test_upgrade_granted_recurses_upgrade_changed_on_leader(
    ctx: Context, base_state: State
) -> None:
    # Given
    state_in = base_state

    # When
    with (
        patch(
            "events.upgrade.KafkaUpgrade.zookeeper_current_version",
            new_callable=PropertyMock,
            return_value="3.6.2",
        ),
        patch("time.sleep"),
        patch("workload.KafkaWorkload.stop"),
        patch("workload.KafkaWorkload.restart"),
        patch("workload.KafkaWorkload.install", return_value=True),
        patch(
            "events.broker.BrokerOperator.healthy", new_callable=PropertyMock, return_value=True
        ),
        patch("workload.BalancerWorkload.stop"),
        patch("events.upgrade.KafkaUpgrade.on_upgrade_changed", autospec=True) as patched_upgrade,
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)
        mock_event = MagicMock()
        charm.broker.upgrade._on_upgrade_granted(mock_event)

    # Then
    patched_upgrade.assert_called_once()
