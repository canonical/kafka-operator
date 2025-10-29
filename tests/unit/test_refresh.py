#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
import logging
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
import yaml
from ops.testing import Container, Context, State

from charm import KafkaCharm
from events.refresh import KafkaUpgradeError, MachinesKafkaRefresh, is_workload_compatible
from literals import CONTAINER, SUBSTRATE

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker


CONFIG = yaml.safe_load(Path("./config.yaml").read_text())
ACTIONS = yaml.safe_load(Path("./actions.yaml").read_text())
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())


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


@pytest.mark.parametrize(
    "old_version,new_version,expected",
    [
        ("3.5.0", "3.6.0", True),  # Minor upgrade allowed
        ("3.5.0", "3.5.1", True),  # Patch upgrade allowed
        ("3.5.0", "4.0.0", False),  # Major upgrade not allowed
        ("3.6.0", "3.5.0", False),  # Downgrade not allowed
        ("invalid", "3.6.0", False),  # Invalid version format
        ("3.5.0", "invalid", False),  # Invalid version format
    ],
)
def test_is_workload_compatible(old_version: str, new_version: str, expected: bool) -> None:
    assert is_workload_compatible(old_version, new_version) == expected


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="snap_refresh not applicable in k8s")
def test_post_snap_refresh_healthy_cluster(ctx: Context, base_state: State) -> None:
    # Given
    state_in = dataclasses.replace(base_state, config=base_state.config)

    # When
    with (ctx(ctx.on.config_changed(), state_in) as manager,):
        charm = cast(KafkaCharm, manager.charm)
        mock_refresh = MagicMock()
        mock_refresh.next_unit_allowed_to_refresh = False

        with patch(
            "events.broker.BrokerOperator.healthy", new_callable=PropertyMock, return_value=True
        ):
            charm.post_snap_refresh(mock_refresh)

            # Then
            assert mock_refresh.next_unit_allowed_to_refresh is True


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="snap_refresh not applicable in k8s")
def test_post_snap_refresh_unhealthy_cluster(ctx: Context, base_state: State) -> None:
    # Given
    state_in = base_state

    # When
    with (ctx(ctx.on.config_changed(), state_in) as manager,):
        charm = cast(KafkaCharm, manager.charm)
        mock_refresh = MagicMock()
        mock_refresh.next_unit_allowed_to_refresh = False

        with patch(
            "events.broker.BrokerOperator.healthy", new_callable=PropertyMock, return_value=False
        ):
            charm.post_snap_refresh(mock_refresh)

            # Then
            assert mock_refresh.next_unit_allowed_to_refresh is False


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="snap_refresh not applicable in k8s")
def test_refresh_snap_successful(ctx: Context, base_state: State) -> None:
    # Given
    state_in = base_state
    snap_name = "kafka"
    snap_revision = "123"

    # When
    with (
        patch("workload.KafkaWorkload.stop") as mock_stop,
        patch("workload.KafkaWorkload.restart") as mock_restart,
        patch("workload.Workload.install", return_value=True) as mock_install,
        patch("managers.config.ConfigManager.set_environment") as mock_set_env,
        patch("charm.KafkaCharm.post_snap_refresh") as mock_post_refresh,
        patch("time.sleep"),
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)
        mock_refresh = MagicMock()

        # Set the revision on the kafka snap mock
        charm.workload.kafka.revision = "456"

        # Mock the MachinesKafkaRefresh constructor to avoid version checks
        with patch("events.refresh.MachinesKafkaRefresh.__init__", return_value=None):
            kafka_refresh = MachinesKafkaRefresh.__new__(MachinesKafkaRefresh)
            kafka_refresh._charm = charm
            kafka_refresh.refresh_snap(
                snap_name=snap_name, snap_revision=snap_revision, refresh=mock_refresh
            )

        # Then
        mock_stop.assert_called_once()
        mock_install.assert_called_once()
        mock_refresh.update_snap_revision.assert_called_once()
        mock_set_env.assert_called_once()
        mock_restart.assert_called_once()
        mock_post_refresh.assert_called_once_with(mock_refresh)


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="snap_refresh not applicable in k8s")
def test_refresh_snap_install_failure_revision_unchanged(ctx: Context, base_state: State) -> None:
    # Given
    state_in = base_state
    snap_name = "kafka"
    snap_revision = "123"
    original_revision = "456"

    # When
    with (
        patch("workload.KafkaWorkload.stop") as mock_stop,
        patch("workload.KafkaWorkload.start") as mock_start,
        patch("workload.Workload.install", return_value=False) as mock_install,
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)
        mock_refresh = MagicMock()

        # Set the revision on the kafka snap mock to remain unchanged
        charm.workload.kafka.revision = original_revision

        # Mock the MachinesKafkaRefresh constructor to avoid version checks
        with patch("events.refresh.MachinesKafkaRefresh.__init__", return_value=None):
            kafka_refresh = MachinesKafkaRefresh.__new__(MachinesKafkaRefresh)
            kafka_refresh._charm = charm

            # Then
            with pytest.raises(KafkaUpgradeError):
                kafka_refresh.refresh_snap(
                    snap_name=snap_name, snap_revision=snap_revision, refresh=mock_refresh
                )

        mock_stop.assert_called_once()
        mock_install.assert_called_once()
        mock_start.assert_called_once()
        mock_refresh.update_snap_revision.assert_not_called()


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="snap_refresh not applicable in k8s")
def test_refresh_snap_install_failure_revision_changed(ctx: Context, base_state: State) -> None:
    # Given
    state_in = base_state
    snap_name = "kafka"
    snap_revision = "123"

    # When
    with (
        patch("workload.KafkaWorkload.stop") as mock_stop,
        patch("workload.KafkaWorkload.start") as mock_start,
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)
        mock_refresh = MagicMock()

        # Set initial revision to something different from snap_revision
        charm.workload.kafka.revision = "initial"

        # Set up install to change revision to target revision and return False
        def change_revision_after_install():
            # This will be called when install() is called
            charm.workload.kafka.revision = snap_revision  # Changed to target revision
            return False  # install() returns False

        # Mock the MachinesKafkaRefresh constructor to avoid version checks
        with (
            patch(
                "workload.Workload.install", side_effect=change_revision_after_install
            ) as mock_install,
            patch("events.refresh.MachinesKafkaRefresh.__init__", return_value=None),
        ):
            kafka_refresh = MachinesKafkaRefresh.__new__(MachinesKafkaRefresh)
            kafka_refresh._charm = charm

            # Then
            with pytest.raises(KafkaUpgradeError):
                kafka_refresh.refresh_snap(
                    snap_name=snap_name, snap_revision=snap_revision, refresh=mock_refresh
                )

        mock_stop.assert_called_once()
        mock_install.assert_called_once()
        mock_start.assert_not_called()
        mock_refresh.update_snap_revision.assert_called_once()
