import dataclasses
import logging
import os
from unittest.mock import PropertyMock, patch

from common.single_kernel_kafka.core.literals import ConnectStatus as Status
from ops.testing import Context, Relation, Resource, State

from .helpers import KAFKA_CLIENT_REL, PLUGIN_PATH

logger = logging.getLogger(__name__)


def test_config_changed_hook_with_no_resource(
    ctx: Context, base_state: State, kafka_client_rel, active_service, restart_rel
) -> None:
    """Checks `config_changed` hook without any resources being attached works."""
    # Given
    state_in = base_state
    kafka_rel = Relation(KAFKA_CLIENT_REL, KAFKA_CLIENT_REL, remote_app_data=kafka_client_rel)

    state_in = dataclasses.replace(base_state, relations=[kafka_rel, restart_rel])

    # When
    state_out = ctx.run(ctx.on.config_changed(), state_in)

    # Then
    assert state_out.unit_status == Status.ACTIVE.value.status


def test_attach_new_plugin_adds_it_to_plugin_path(
    ctx: Context, base_state: State, plugin_resource: Resource
) -> None:
    """Checks attaching a new plugin resource leads to it being un-tarred and added to `PLUGIN_PATH`."""
    # Given
    state_in = base_state
    state_in = dataclasses.replace(base_state, resources={plugin_resource})

    # When
    with (
        patch("single_kernel_kafka.managers.connect.ConnectManager._untar_plugin") as _fake_untar,
        patch(
            "single_kernel_kafka.managers.connect.ConnectManager._plugin_checksum"
        ) as _fake_checksum,
    ):
        _ = ctx.run(ctx.on.config_changed(), state_in)

    # Then
    assert _fake_checksum.call_count
    assert _fake_untar.call_count
    assert os.path.basename(f"{_fake_untar.call_args[0][0]}") in f"{plugin_resource.path}"
    assert PLUGIN_PATH in f"{_fake_untar.call_args[0][1]}"


def test_attach_existing_plugin_skips(
    ctx: Context, base_state: State, plugin_resource: Resource
) -> None:
    """Checks attaching an already existing plugin resource leads to no-op."""
    # Given
    state_in = base_state
    state_in = dataclasses.replace(base_state, resources={plugin_resource})

    # When
    with (
        patch("single_kernel_kafka.managers.connect.ConnectManager._untar_plugin") as _fake_untar,
        patch(
            "single_kernel_kafka.managers.connect.ConnectManager._plugin_checksum",
            return_value="checksum",
        ) as _fake_checksum,
        patch(
            "single_kernel_kafka.managers.connect.ConnectManager.plugins_cache",
            PropertyMock(return_value={"checksum"}),
        ),
    ):
        _ = ctx.run(ctx.on.config_changed(), state_in)

    # Then
    assert _fake_checksum.call_count == 1
    assert _fake_untar.call_count == 0
