#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
import json
import logging
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from charms.data_platform_libs.v1.upgrade import ClusterNotReadyError, DependencyModel
from ops.testing import Context, PeerRelation, State
from single_kernel_kafka.core.literals import CONNECT_DEPENDENCIES as DEPENDENCIES
from single_kernel_kafka.events.connect.upgrade import ConnectDependencyModel

from .helpers import CONFIG, PEER_REL, SUBSTRATE, SUBSTRATE_CLS, ConnectCharm

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker


@pytest.fixture()
def charm_configuration():
    """Enable direct mutation on configuration dict."""
    return json.loads(json.dumps(CONFIG))


@pytest.fixture()
def upgrade_func() -> str:
    if SUBSTRATE == "k8s":
        return "_on_connect_pebble_ready_upgrade"

    return "_on_upgrade_granted"


def test_pre_upgrade_check_raises_not_healthy(
    ctx: Context, base_state: State, dead_service
) -> None:
    # Given
    state_in = base_state

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(ConnectCharm, manager.charm)
        charm.connect_manager.health_check = lambda: False

        with pytest.raises(ClusterNotReadyError):
            charm.upgrade.pre_upgrade_check()


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="machine-specific test.")
def test_pre_upgrade_check_succeeds(ctx: Context, base_state: State, active_service) -> None:
    # Given
    state_in = base_state

    # When
    with (
        patch(
            "single_kernel_kafka.events.connect.upgrade.ConnectUpgradeMachine._set_rolling_update_partition"
        ),
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(ConnectCharm, manager.charm)

        # Then
        charm.upgrade.pre_upgrade_check()


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="upgrade stack not used on K8s")
def test_build_upgrade_stack(ctx: Context, base_state: State) -> None:
    # Given
    cluster_peer = PeerRelation(
        PEER_REL,
        PEER_REL,
        local_unit_data={"private-address": "000.000.000"},
        peers_data={1: {"private-address": "111.111.111"}, 2: {"private-address": "222.222.222"}},
    )
    state_in = dataclasses.replace(base_state, relations=[cluster_peer])

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(ConnectCharm, manager.charm)
        stack = charm.upgrade.build_upgrade_stack()

    # Then
    assert len(stack) == 3
    assert len(stack) == len(set(stack))


def test_connect_dependency_model():
    assert sorted(ConnectDependencyModel.__fields__.keys()) == sorted(DEPENDENCIES.keys())

    for value in DEPENDENCIES.values():
        assert DependencyModel(**value)


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="Upgrade granted not used on K8s charms")
def test_upgrade_granted_sets_failed_if_failed_snap(ctx: Context, base_state: State) -> None:
    # Given
    state_in = base_state

    # Then
    with (
        patch(f"single_kernel_kafka.workload.ConnectWorkload{SUBSTRATE_CLS}.stop") as patched_stop,
        patch(
            f"single_kernel_kafka.workload.ConnectWorkload{SUBSTRATE_CLS}.install",
            return_value=False,
        ),
        patch(
            "single_kernel_kafka.events.connect.upgrade.ConnectUpgradeMachine.set_unit_failed",
        ) as patch_set_failed,
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(ConnectCharm, manager.charm)
        mock_event = MagicMock()
        charm.upgrade._on_upgrade_granted(mock_event)

    # Then
    patched_stop.assert_called_once()
    assert patch_set_failed.call_count


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="machine-specific test")
def test_upgrade_sets_failed_if_failed_upgrade_check(
    ctx: Context, base_state: State, upgrade_func: str, dead_service
) -> None:
    # Given
    state_in = base_state

    # When
    with (
        patch(
            f"single_kernel_kafka.workload.ConnectWorkload{SUBSTRATE_CLS}.restart"
        ) as patched_restart,
        patch(
            f"single_kernel_kafka.workload.ConnectWorkload{SUBSTRATE_CLS}.start"
        ) as patched_start,
        patch(f"single_kernel_kafka.workload.ConnectWorkload{SUBSTRATE_CLS}.stop"),
        patch(f"single_kernel_kafka.workload.ConnectWorkload{SUBSTRATE_CLS}.install"),
        patch("single_kernel_kafka.core.connect_models.ConnectContext.ready", return_value=True),
        patch(
            "single_kernel_kafka.events.connect.upgrade.ConnectUpgradeMachine.set_unit_failed",
        ) as patch_set_failed,
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(ConnectCharm, manager.charm)
        mock_event = MagicMock()
        getattr(charm.upgrade, upgrade_func)(mock_event)

    # Then
    assert patched_restart.call_count or patched_start.call_count
    assert patch_set_failed.call_count


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="Upgrade granted not used on K8s charms")
def test_upgrade_succeeds(
    ctx: Context, base_state: State, upgrade_func: str, active_service
) -> None:
    # Given
    state_in = base_state

    # When
    with (
        patch(
            f"single_kernel_kafka.workload.ConnectWorkload{SUBSTRATE_CLS}.restart"
        ) as patched_restart,
        patch(
            f"single_kernel_kafka.workload.ConnectWorkload{SUBSTRATE_CLS}.start"
        ) as patched_start,
        patch(f"single_kernel_kafka.workload.ConnectWorkload{SUBSTRATE_CLS}.stop"),
        patch(f"single_kernel_kafka.workload.ConnectWorkload{SUBSTRATE_CLS}.install"),
        patch("single_kernel_kafka.core.connect_models.ConnectContext.ready", return_value=True),
        patch(
            "single_kernel_kafka.events.connect.upgrade.ConnectUpgradeMachine.set_unit_completed",
        ) as patch_set_completed,
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(ConnectCharm, manager.charm)
        mock_event = MagicMock()
        getattr(charm.upgrade, upgrade_func)(mock_event)

    assert patched_restart.call_count or patched_start.call_count
    assert patch_set_completed.call_count


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="Upgrade granted not used on K8s charms")
def test_upgrade_granted_recurses_upgrade_changed_on_leader(
    ctx: Context, base_state: State, active_service
) -> None:
    # Given
    state_in = base_state

    # When
    with (
        patch(f"single_kernel_kafka.workload.ConnectWorkload{SUBSTRATE_CLS}.restart"),
        patch(f"single_kernel_kafka.workload.ConnectWorkload{SUBSTRATE_CLS}.start"),
        patch(f"single_kernel_kafka.workload.ConnectWorkload{SUBSTRATE_CLS}.stop"),
        patch(f"single_kernel_kafka.workload.ConnectWorkload{SUBSTRATE_CLS}.install"),
        patch("single_kernel_kafka.core.connect_models.ConnectContext.ready", return_value=True),
        patch(
            "single_kernel_kafka.events.connect.upgrade.ConnectUpgradeMachine.on_upgrade_changed",
            autospec=True,
        ) as patched_upgrade,
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(ConnectCharm, manager.charm)
        mock_event = MagicMock()
        charm.upgrade._on_upgrade_granted(mock_event)

    # Then
    patched_upgrade.assert_called_once()
