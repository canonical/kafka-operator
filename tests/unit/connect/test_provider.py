import dataclasses
import logging
from typing import cast
from unittest.mock import MagicMock

import pytest
from charms.data_platform_libs.v0.data_interfaces import (
    PLUGIN_URL_NOT_REQUIRED,
    IntegrationRequestedEvent,
)
from common.single_kernel_kafka.core.literals import ConnectStatus as Status
from ops.testing import Context, PeerRelation, Relation, Secret, State

from .helpers import CLIENT_REL, PEER_REL, ConnectCharm

logger = logging.getLogger(__name__)


@pytest.mark.parametrize(
    "plugin_url",
    [PLUGIN_URL_NOT_REQUIRED, "mellon"],
    ids=[f"plugin_url {PLUGIN_URL_NOT_REQUIRED}", "pugin_url"],
)
def test_integration_requested(
    ctx: Context, base_state: State, active_service: MagicMock, plugin_url
) -> None:
    """Checks the `integration_requested` event triggers creation of credentials on the provider side."""
    # Given
    relation_id = 7
    state_in = base_state
    client_rel = Relation(
        CLIENT_REL,
        CLIENT_REL,
        id=relation_id,
        remote_app_data={"plugin-url": plugin_url},
    )
    peer_rel = PeerRelation(PEER_REL, PEER_REL)
    event = IntegrationRequestedEvent(
        handle=MagicMock(), relation=client_rel  # pyright: ignore[reportArgumentType]
    )
    connect_manager_mock = MagicMock()
    auth_manager_mock = MagicMock()

    state_in = dataclasses.replace(base_state, relations=[peer_rel, client_rel])

    # When
    with (ctx(ctx.on.update_status(), state_in) as mgr,):
        charm = cast(ConnectCharm, mgr.charm)
        charm.connect_manager = connect_manager_mock
        charm.auth_manager = auth_manager_mock

        charm.connect.provider._on_integration_requested(event)
        state_out = mgr.run()

        # Then
        if plugin_url == PLUGIN_URL_NOT_REQUIRED:
            assert not charm.connect_manager.load_plugin_from_url.call_count
        else:
            assert charm.connect_manager.load_plugin_from_url.call_count

    client_rel_out = state_out.get_relation(client_rel.id)
    peer_rel_out = state_out.get_relation(peer_rel.id)

    assert client_rel_out.local_app_data.get("username") == f"relation-{relation_id}"
    assert client_rel_out.local_app_data.get("password")
    assert peer_rel_out.local_unit_data.get("restart") == "true"
    assert auth_manager_mock.update.call_count == 1
    assert state_out.unit_status == Status.MISSING_KAFKA.value.status


@pytest.mark.parametrize("is_leader", [True, False])
@pytest.mark.parametrize("initial_data", [{}, {"username": "relation-7", "password": "password"}])
def test_provider_on_relation_changed(
    ctx: Context, base_state: State, is_leader: bool, initial_data: dict, active_service: MagicMock
) -> None:
    """Checks `realtion_changed` event handling logic based on leadership status and whether credentials has been created on the leader or not."""
    # Given
    relation_id = 7
    state_in = base_state
    if initial_data:
        secret = Secret(
            label=f"connect-client.{relation_id}.user.secret",
            tracked_content=initial_data,
        )
        secrets = [secret]
    else:
        secrets = []
    client_rel = Relation(
        CLIENT_REL,
        CLIENT_REL,
        id=relation_id,
        remote_app_data={"plugin-url": "http://10.10.10.10:8080"},
        remote_units_data={0: initial_data | {"secret-user": secret.id} if secrets else {}},
    )
    peer_rel = PeerRelation(PEER_REL, PEER_REL)
    connect_manager_mock = MagicMock()
    auth_manager_mock = MagicMock()

    state_in = dataclasses.replace(
        base_state, relations=[peer_rel, client_rel], leader=is_leader, secrets=secrets
    )

    # When
    with ctx(ctx.on.relation_changed(client_rel), state_in) as mgr:
        charm = cast(ConnectCharm, mgr.charm)
        charm.connect_manager = connect_manager_mock
        charm.auth_manager = auth_manager_mock
        state_out = mgr.run()

    # Then

    peer_rel_out = state_out.get_relation(peer_rel.id)

    if initial_data:
        assert peer_rel_out.local_unit_data.get("restart") == "true"
        assert charm.context.clients[relation_id].password == "password"
        assert auth_manager_mock.update.call_count > 0

    deferred_count = 2 if is_leader and not initial_data else 1
    assert len(state_out.deferred) == deferred_count
    assert state_out.unit_status == Status.MISSING_KAFKA.value.status


def test_provider_on_relation_joined(ctx: Context, base_state: State, active_service) -> None:
    """Checks `realtion_joined` event leads to loading of plugins on the provider side."""
    # Given
    relation_id = 7
    plugin_url = "http://10.10.10.10:8080"
    state_in = base_state
    client_rel = Relation(
        CLIENT_REL,
        CLIENT_REL,
        id=relation_id,
        remote_app_data={"plugin-url": plugin_url},
    )
    peer_rel = PeerRelation(PEER_REL, PEER_REL)
    connect_manager_mock = MagicMock()

    state_in = dataclasses.replace(base_state, relations=[peer_rel, client_rel], leader=False)

    # When
    with ctx(ctx.on.relation_joined(client_rel), state_in) as mgr:
        charm = cast(ConnectCharm, mgr.charm)
        charm.connect_manager = connect_manager_mock
        state_out = mgr.run()

    # Then
    assert connect_manager_mock.load_plugin_from_url.call_count == 1
    assert plugin_url in connect_manager_mock.load_plugin_from_url.call_args.args
    assert state_out.unit_status == Status.MISSING_KAFKA.value.status


def test_provider_on_relation_broken(ctx: Context, base_state: State, active_service) -> None:
    """Checks on `relation_broken` all related credentials and plugins are removed from the provider."""
    # Given
    relation_id = 7
    state_in = base_state
    client_rel = Relation(
        CLIENT_REL,
        CLIENT_REL,
        id=relation_id,
        remote_app_data={"plugin-url": "http://10.10.10.10:8080"},
    )
    peer_rel = PeerRelation(PEER_REL, PEER_REL)
    connect_manager_mock = MagicMock()
    auth_manager_mock = MagicMock()

    state_in = dataclasses.replace(base_state, relations=[peer_rel, client_rel])

    # When
    with ctx(ctx.on.relation_broken(client_rel), state_in) as mgr:
        charm = cast(ConnectCharm, mgr.charm)
        charm.connect_manager = connect_manager_mock
        charm.auth_manager = auth_manager_mock
        state_out = mgr.run()

    # Then
    assert connect_manager_mock.remove_plugin.call_count == 1
    assert (
        connect_manager_mock.remove_plugin.call_args.kwargs["path_prefix"]
        == f"relation-{relation_id}"
    )
    assert auth_manager_mock.remove_user.call_count == 1
    assert f"relation-{relation_id}" in auth_manager_mock.remove_user.call_args.args
    assert state_out.unit_status == Status.MISSING_KAFKA.value.status
