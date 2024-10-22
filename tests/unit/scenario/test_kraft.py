#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from ops import ActiveStatus
from scenario import Container, Context, PeerRelation, Relation, State

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
    state_in = State(leader=True, relations=[])

    # When
    state_out = ctx.run("start", state_in)

    # Then
    assert state_out.unit_status == Status.NO_PEER_RELATION.value.status


def test_ready_to_start_no_peer_cluster(charm_configuration):
    # Given
    charm_configuration["options"]["roles"]["default"] = "controller"
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    cluster_peer = PeerRelation(PEER, PEER)
    state_in = State(leader=True, relations=[cluster_peer])

    # When
    state_out = ctx.run("start", state_in)

    # Then
    assert state_out.unit_status == Status.NO_PEER_CLUSTER_RELATION.value.status


def test_ready_to_start_missing_data_as_controller(charm_configuration, base_state: State):
    # Given
    charm_configuration["options"]["roles"]["default"] = "controller"
    charm_configuration["options"]["expose-external"]["default"] = "none"
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    cluster_peer = PeerRelation(PEER, PEER)
    peer_cluster = Relation(PEER_CLUSTER_RELATION, "peer_cluster")
    state_in = base_state.replace(relations=[cluster_peer, peer_cluster])

    # When
    state_out = ctx.run("start", state_in)

    # Then
    assert state_out.unit_status == Status.NO_BROKER_DATA.value.status


def test_ready_to_start_missing_data_as_broker(charm_configuration, base_state: State):
    # Given
    charm_configuration["options"]["roles"]["default"] = "broker"
    charm_configuration["options"]["expose-external"]["default"] = "none"
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
    state_in = base_state.replace(relations=[cluster_peer, peer_cluster])

    # When
    with patch("workload.KafkaWorkload.run_bin_command", return_value="cluster-uuid-number"):
        state_out = ctx.run("start", state_in)

    # Then
    assert state_out.unit_status == Status.NO_QUORUM_URIS.value.status


def test_ready_to_start(charm_configuration, base_state: State):
    # Given
    charm_configuration["options"]["roles"]["default"] = "broker,controller"
    charm_configuration["options"]["expose-external"]["default"] = "none"
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    cluster_peer = PeerRelation(PEER, PEER)
    state_in = base_state.replace(relations=[cluster_peer])

    # When
    with (
        patch(
            "workload.KafkaWorkload.run_bin_command", return_value="cluster-uuid-number"
        ) as patched_run_bin_command,
        patch("health.KafkaHealth.machine_configured", return_value=True),
        patch("workload.KafkaWorkload.start"),
        patch("charms.operator_libs_linux.v1.snap.SnapCache"),
    ):
        state_out = ctx.run("start", state_in)

    # Then
    # Second call of format will have to pass "cluster-uuid-number" as set above
    assert "cluster-uuid-number" in patched_run_bin_command.call_args_list[1][1]["bin_args"]
    assert "cluster-uuid" in state_out.get_relations(PEER)[0].local_app_data
    assert "controller-quorum-uris" in state_out.get_relations(PEER)[0].local_app_data
    # Only the internal users should be created.
    # FIXME: This is a convoluted way to unpack secret contents.
    # In scenario v7 use "tracked_content" instead to access last revision directly
    assert all(
        user in sorted(state_out.secrets[0].contents.items())[-1][1]
        for user in ("admin-password", "sync-password")
    )
    assert state_out.unit_status == ActiveStatus()
