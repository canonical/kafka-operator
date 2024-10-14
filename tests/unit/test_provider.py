#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
import logging
from pathlib import Path
from unittest.mock import PropertyMock, patch

import pytest
import yaml
from scenario import Container, Context, PeerRelation, Relation, Secret, State

from charm import KafkaCharm
from literals import (
    CONTAINER,
    PEER,
    REL_NAME,
    SUBSTRATE,
    ZK,
)

pytestmark = pytest.mark.broker


logger = logging.getLogger(__name__)


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


def test_client_relation_created_defers_if_not_ready(ctx: Context, base_state: State) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    zk_relation = Relation(ZK, ZK)
    client_relation = Relation(
        REL_NAME,
        "app",
        remote_app_data={"topic": "TOPIC", "extra-user-roles": "consumer,producer"},
    )
    state_in = dataclasses.replace(
        base_state, relations=[cluster_peer, zk_relation, client_relation]
    )

    # When
    with (
        patch(
            "events.broker.BrokerOperator.healthy", new_callable=PropertyMock, return_value=False
        ),
        patch("managers.auth.AuthManager.add_user") as patched_add_user,
        patch("ops.framework.EventBase.defer") as patched_defer,
    ):
        ctx.run(ctx.on.relation_changed(client_relation), state_in)

    # Then
    patched_add_user.assert_not_called()
    patched_defer.assert_called()


def test_client_relation_created_adds_user(ctx: Context, base_state: State) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    zk_relation = Relation(ZK, ZK)
    client_relation = Relation(
        REL_NAME,
        "app",
        remote_app_data={"topic": "TOPIC", "extra-user-roles": "consumer,producer"},
    )
    state_in = dataclasses.replace(
        base_state, relations=[cluster_peer, zk_relation, client_relation]
    )

    # When
    with (
        patch(
            "events.broker.BrokerOperator.healthy", new_callable=PropertyMock, return_value=True
        ),
        patch("managers.auth.AuthManager.add_user") as patched_add_user,
        patch("workload.KafkaWorkload.run_bin_command"),
        patch("core.cluster.ZooKeeper.connect", new_callable=PropertyMock, return_value="yes"),
    ):
        state_out = ctx.run(ctx.on.relation_changed(client_relation), state_in)

    # Then
    patched_add_user.assert_called_once()
    assert f"relation-{client_relation.id}" in next(iter(state_out.secrets)).tracked_content


def test_client_relation_broken_removes_user(ctx: Context, base_state: State) -> None:
    """Checks if users are removed on clientrelationbroken hook."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    zk_relation = Relation(ZK, ZK)
    client_relation = Relation(
        REL_NAME,
        "app",
        remote_app_data={"topic": "TOPIC", "extra-user-roles": "consumer,producer"},
    )
    secret = Secret(
        tracked_content={f"relation-{client_relation.id}": "password"},
        owner="app",
        label="cluster.kafka-k8s.app" if SUBSTRATE == "k8s" else "cluster.kafka.app",
    )
    state_in = dataclasses.replace(
        base_state, relations=[cluster_peer, zk_relation, client_relation], secrets=[secret]
    )

    # When
    with (
        patch(
            "events.broker.BrokerOperator.healthy", new_callable=PropertyMock, return_value=True
        ),
        patch("managers.auth.AuthManager.add_user"),
        patch("managers.auth.AuthManager.delete_user") as patched_delete_user,
        patch("managers.auth.AuthManager.remove_all_user_acls") as patched_remove_acls,
        patch("workload.KafkaWorkload.run_bin_command"),
        patch("core.cluster.ZooKeeper.connect", new_callable=PropertyMock, return_value="yes"),
    ):
        state_out = ctx.run(ctx.on.relation_broken(client_relation), state_in)

    # Then
    patched_remove_acls.assert_called_once()
    patched_delete_user.assert_called_once()
    # validating username got removed, by removing the full secret
    assert not state_out.secrets


def test_client_relation_joined_sets_necessary_relation_data(
    ctx: Context, base_state: State
) -> None:
    """Checks if all needed provider relation data is set on clientrelationjoined hook."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    zk_relation = Relation(ZK, ZK)
    client_relation = Relation(
        REL_NAME,
        "app",
        remote_app_data={"topic": "TOPIC", "extra-user-roles": "consumer,producer"},
    )
    state_in = dataclasses.replace(
        base_state, relations=[cluster_peer, zk_relation, client_relation]
    )

    # When
    with (
        patch(
            "events.broker.BrokerOperator.healthy", new_callable=PropertyMock, return_value=True
        ),
        patch("managers.auth.AuthManager.add_user"),
        patch("workload.KafkaWorkload.run_bin_command"),
        patch("core.models.ZooKeeper.uris", new_callable=PropertyMock, return_value="yes"),
    ):
        state_out = ctx.run(ctx.on.relation_changed(client_relation), state_in)

    # Then
    relation_databag = state_out.get_relation(client_relation.id).local_app_data
    assert not {
        "username",
        "password",
        "tls-ca",
        "endpoints",
        "data",
        "zookeeper-uris",
        "consumer-group-prefix",
        "tls",
        "topic",
    } - set(relation_databag.keys())

    assert relation_databag.get("tls", None) == "disabled"
    assert relation_databag.get("zookeeper-uris", None) == "yes"
    assert relation_databag.get("username", None) == f"relation-{client_relation.id}"
    assert relation_databag.get("consumer-group-prefix", None) == f"relation-{client_relation.id}-"
