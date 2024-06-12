#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
from pathlib import Path
from unittest.mock import PropertyMock, patch

import pytest
import yaml
from ops import ActiveStatus
from scenario import Context, PeerRelation, Relation, State

from charm import KafkaCharm
from literals import (
    ADMIN_USER,
    BALANCER,
    BALANCER_RELATION,
    BALANCER_SERVICE,
    BALANCER_TOPIC,
    BROKER,
    PEER,
    Status,
)

pytestmark = pytest.mark.balancer

logger = logging.getLogger(__name__)


CONFIG = yaml.safe_load(Path("./config.yaml").read_text())
ACTIONS = yaml.safe_load(Path("./actions.yaml").read_text())
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())


@pytest.fixture()
def charm_configuration():
    """Enable direct mutation on configuration dict."""
    return json.loads(json.dumps(CONFIG))


def test_install_blocks_snap_install_failure(charm_configuration):
    # Given
    charm_configuration["options"]["role"]["default"] = "balancer"
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    state_in = State()

    # When
    with patch("workload.Workload.install", return_value=False):
        state_out = ctx.run("install", state_in)

    # Then
    assert state_out.unit_status == Status.SNAP_NOT_INSTALLED.value.status


def test_ready_to_start_maintenance_no_peer_relation(charm_configuration):
    # Given
    charm_configuration["options"]["role"]["default"] = "balancer"
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


def test_ready_to_start_maintenance_no_broker_relation(charm_configuration):
    # Given
    charm_configuration["options"]["role"]["default"] = "balancer"
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    peer = PeerRelation(PEER, PEER)
    state_in = State(leader=True, relations=[peer])

    # When
    state_out = ctx.run("start", state_in)

    # Then
    assert state_out.unit_status == Status.BROKER_NOT_RELATED.value.status


def test_ready_to_start_ok(charm_configuration):
    # Given
    charm_configuration["options"]["role"]["default"] = "balancer"
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    peer = PeerRelation(PEER, PEER)
    relation = Relation(
        interface=BALANCER.value,
        endpoint=BALANCER_SERVICE,
        remote_app_name=BROKER.value,
    )
    state_in = State(leader=True, relations=[peer, relation])

    # When
    with patch("workload.Workload.write"), patch("workload.BalancerWorkload.start"):
        state_out = ctx.run("start", state_in)

    # Then
    assert state_out.unit_status == ActiveStatus()


def test_secrets_requested_by_balancer_on_relation_creation(charm_configuration):
    # Given
    charm_configuration["options"]["role"]["default"] = "balancer"
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    peer = PeerRelation(PEER, PEER)
    relation = Relation(
        interface=BALANCER.value,
        endpoint=BALANCER_SERVICE,
        remote_app_name=BROKER.value,
    )
    state_in = State(leader=True, relations=[peer, relation])

    # When
    state_out = ctx.run(relation.created_event, state_in)

    # Then
    assert (
        json.loads(state_out.relations[1].local_app_data["requested-secrets"])
        == BALANCER.requested_secrets
    )


def test_broker_relation_broken_stops_service(charm_configuration):
    # Given
    charm_configuration["options"]["role"]["default"] = "balancer"
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    peer = PeerRelation(PEER, PEER)
    relation = Relation(
        interface=BALANCER.value,
        endpoint=BALANCER_SERVICE,
        remote_app_name=BROKER.value,
        local_app_data={
            "requested-secrets": json.dumps(BALANCER.requested_secrets),
            "topic": BALANCER_TOPIC,
            "extra-user-roles": ADMIN_USER,
        },
        remote_app_data={},
    )
    state_in = State(leader=True, relations=[peer, relation])

    # When
    with patch("workload.BalancerWorkload.stop") as patched_stop_snap_service:
        state_out = ctx.run(relation.broken_event, state_in)

    patched_stop_snap_service.assert_called_once()
    assert state_out.unit_status == Status.BROKER_NOT_RELATED.value.status


def test_balancer_relation_created_defers_if_not_ready(charm_configuration):
    """Checks event is deferred if not ready on balancer relation created hook."""
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    peer = PeerRelation(PEER, PEER)
    relation = Relation(
        interface=BROKER.value,
        endpoint=BALANCER_RELATION,
        remote_app_name=BALANCER.value,
        remote_app_data={
            "requested-secrets": json.dumps(BALANCER.requested_secrets),
            "topic": BALANCER_TOPIC,
            "extra-user-roles": ADMIN_USER,
        },
    )
    state_in = State(leader=True, relations=[peer, relation])

    # When
    with (
        patch("charm.KafkaCharm.healthy", new_callable=PropertyMock, return_value=False),
        patch("managers.auth.AuthManager.add_user") as patched_add_user,
        patch("ops.framework.EventBase.defer") as patched_defer,
    ):
        _ = ctx.run(relation.changed_event, state_in)

    # Then
    patched_add_user.assert_not_called()
    patched_defer.assert_called()
