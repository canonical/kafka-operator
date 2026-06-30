#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
import logging
from typing import cast
from unittest.mock import PropertyMock, patch

import pytest
from charms.data_platform_libs.v0.data_interfaces import PLUGIN_URL_NOT_REQUIRED
from ops.testing import Context, PeerRelation, Relation, State

from .helpers import CLIENT_REL, KAFKA_CLIENT_REL, PEER_REL, ConnectCharm

logger = logging.getLogger(__name__)


@pytest.mark.parametrize(
    "plugin_url",
    [PLUGIN_URL_NOT_REQUIRED, "mellon"],
    ids=[f"plugin_url {PLUGIN_URL_NOT_REQUIRED}", "pugin_url"],
)
def test_update_plugins(ctx: Context, base_state: State, plugin_url) -> None:
    f"""Test update_plugins does not attempt to load plugin from url if {PLUGIN_URL_NOT_REQUIRED}"""
    # Given
    relation_id = 7
    state_in = base_state
    client_rel = Relation(
        CLIENT_REL,
        CLIENT_REL,
        id=relation_id,
        remote_app_data={"plugin-url": plugin_url},
    )
    peer_rel = PeerRelation(PEER_REL, PEER_REL, local_app_data={})
    state_in = dataclasses.replace(base_state, relations=[peer_rel, client_rel])

    # When
    with (
        ctx(ctx.on.config_changed(), state_in) as manager,
        patch(
            "single_kernel_kafka.managers.connect.ConnectManager.load_plugin_from_url"
        ) as patched_load_plugin,
    ):
        _ = cast(ConnectCharm, manager.charm)
        manager.charm.connect.update_plugins()

        # Then
        if plugin_url == PLUGIN_URL_NOT_REQUIRED:
            assert not patched_load_plugin.call_count
        else:
            assert patched_load_plugin.call_count


@pytest.mark.parametrize(
    "plugin_url",
    [PLUGIN_URL_NOT_REQUIRED, "mellon"],
    ids=[f"plugin_url {PLUGIN_URL_NOT_REQUIRED}", "pugin_url missing username"],
)
def test_config_changed_update_clients_data(
    ctx: Context, base_state: State, plugin_url, kafka_client_rel, active_service, restart_rel
) -> None:
    """Checks config-changed updates client relation data without plugin-url set."""
    # Given
    state_in = base_state
    client_rel = Relation(
        CLIENT_REL,
        CLIENT_REL,
        remote_app_data={"plugin-url": plugin_url},
    )
    peer_rel = PeerRelation(PEER_REL, PEER_REL, local_app_data={})
    kafka_rel = Relation(KAFKA_CLIENT_REL, KAFKA_CLIENT_REL, remote_app_data=kafka_client_rel)
    state_in = dataclasses.replace(
        base_state, relations=[client_rel, kafka_rel, peer_rel, restart_rel]
    )

    # When
    with (
        patch(
            "single_kernel_kafka.core.connect_models.ConnectClientContext.update"
        ) as patched_update,
        patch(
            "single_kernel_kafka.core.connect_models.ConnectClientContext.password",
            new_callable=PropertyMock,
            return_value="mellon",
        ),
    ):
        _ = ctx.run(ctx.on.config_changed(), state_in)

    # Then
    if plugin_url == PLUGIN_URL_NOT_REQUIRED:
        assert patched_update.call_count
    else:
        assert not patched_update.call_count
