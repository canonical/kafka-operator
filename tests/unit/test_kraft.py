#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from ops import ActiveStatus
from ops.testing import Container, Context, PeerRelation, Relation, State

from charm import KafkaCharm
from literals import (
    CONTAINER,
    PEER,
    PEER_CLUSTER_ORCHESTRATOR_RELATION,
    PEER_CLUSTER_RELATION,
    SUBSTRATE,
    Status,
)

pytestmark = pytest.mark.kraft

logger = logging.getLogger(__name__)


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


def test_ready_to_start_maintenance_no_peer_relation(charm_configuration, base_state: State):
    # Given
    charm_configuration["options"]["roles"]["default"] = "controller"
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    state_in = base_state

    # When
    state_out = ctx.run(ctx.on.start(), state_in)

    # Then
    assert state_out.unit_status == Status.NO_PEER_RELATION.value.status


def test_ready_to_start_no_peer_cluster(charm_configuration, base_state: State):
    # Given
    charm_configuration["options"]["roles"]["default"] = "controller"
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    cluster_peer = PeerRelation(PEER, PEER)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer])

    # When
    state_out = ctx.run(ctx.on.start(), state_in)

    # Then
    assert state_out.unit_status == Status.NO_PEER_CLUSTER_RELATION.value.status


def test_ready_to_start_missing_data_as_controller(charm_configuration, base_state: State):
    # Given
    charm_configuration["options"]["roles"]["default"] = "controller"
    charm_configuration["options"]["expose-external"]["default"] = "false"
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    cluster_peer = PeerRelation(PEER, PEER)
    peer_cluster = Relation(PEER_CLUSTER_RELATION, "peer_cluster")
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, peer_cluster])

    # When
    state_out = ctx.run(ctx.on.start(), state_in)

    # Then
    assert state_out.unit_status == Status.NO_BROKER_DATA.value.status


def test_ready_to_start_missing_data_as_broker(charm_configuration, base_state: State):
    # Given
    charm_configuration["options"]["roles"]["default"] = "broker"
    charm_configuration["options"]["expose-external"]["default"] = "false"
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    cluster_peer = PeerRelation(PEER, PEER)
    peer_cluster = Relation(
        PEER_CLUSTER_ORCHESTRATOR_RELATION, "peer_cluster", remote_app_data={"roles": "controller"}
    )
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, peer_cluster])

    # When
    with patch("workload.KafkaWorkload.run_bin_command", return_value="cluster-uuid-number"):
        state_out = ctx.run(ctx.on.start(), state_in)

    # Then
    assert state_out.unit_status == Status.NO_QUORUM_URIS.value.status


def test_ready_to_start(charm_configuration, base_state: State):
    # Given
    charm_configuration["options"]["roles"]["default"] = "broker,controller"
    charm_configuration["options"]["expose-external"]["default"] = "false"
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    cluster_peer = PeerRelation(PEER, PEER)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer])

    # When
    with (
        patch(
            "workload.KafkaWorkload.run_bin_command", return_value="cluster-uuid-number"
        ) as patched_run_bin_command,
        patch("health.KafkaHealth.machine_configured", return_value=True),
        patch("workload.KafkaWorkload.start"),
        patch("workload.KafkaWorkload.active", return_value=True),
        patch("charms.operator_libs_linux.v1.snap.SnapCache"),
    ):
        state_out = ctx.run(ctx.on.start(), state_in)

    # Then
    # Second call of format will have to pass "cluster-uuid-number" as set above
    assert "cluster-uuid-number" in patched_run_bin_command.call_args_list[1][1]["bin_args"]
    assert "cluster-uuid" in state_out.get_relations(PEER)[0].local_app_data
    assert "controller-quorum-uris" in state_out.get_relations(PEER)[0].local_app_data
    # Only the internal users should be created.
    assert "admin-password" in next(iter(state_out.secrets)).latest_content
    assert "sync-password" in next(iter(state_out.secrets)).latest_content
    assert state_out.unit_status == ActiveStatus(), logger.error(f"{state_out.unit_status=}")
