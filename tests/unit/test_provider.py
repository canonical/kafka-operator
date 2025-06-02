#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
import logging
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
import yaml
from ops.testing import Container, Context, PeerRelation, Relation, Secret, State
from tests.unit.helpers import TLSArtifacts

from charm import KafkaCharm
from literals import (
    CONTAINER,
    PEER,
    REL_NAME,
    SUBSTRATE,
    ZK,
    Status,
)
from managers.auth import AuthManager

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
        patch(
            "managers.tls.TLSManager.trusted_certificates",
            new_callable=PropertyMock,
            return_value=[],
        ),
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


# -- MTLS tests --


def test_mtls_without_tls_relation(
    ctx: Context, base_state: State, zk_data: dict[str, str]
) -> None:
    # Given
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data)
    restart_relation = PeerRelation("restart", "rolling_op")
    client_rel_id = 11
    client_relation = Relation(
        REL_NAME,
        "app",
        id=client_rel_id,
        remote_app_data={
            "topic": "TOPIC",
            "extra-user-roles": "consumer,producer",
            "mtls-cert": "cert",
        },
    )
    cluster_peer = PeerRelation(
        PEER,
        PEER,
        local_app_data={f"relation-{client_relation.id}": "password"},
    )
    state_in = dataclasses.replace(
        base_state,
        relations=[cluster_peer, client_relation, restart_relation, zk_relation],
    )

    with (
        patch("workload.KafkaWorkload.read", return_value=["key=value"]),
        patch(
            "events.broker.BrokerOperator.healthy", new_callable=PropertyMock, return_value=True
        ),
        # Model props
        patch("core.models.KafkaCluster.internal_user_credentials"),
        patch(
            "core.models.ZooKeeper.zookeeper_connected",
            new_callable=PropertyMock,
            return_value=True,
        ),
    ):
        state_out = ctx.run(ctx.on.relation_changed(client_relation), state_in)

    # Then
    assert state_out.app_status == Status.MTLS_REQUIRES_TLS.value.status


@pytest.mark.parametrize("tls_artifacts", [False, True], indirect=True)
def test_mtls_setup(
    ctx: Context, base_state: State, zk_data: dict[str, str], tls_artifacts: TLSArtifacts
) -> None:
    # Given
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data)
    restart_relation = PeerRelation("restart", "rolling_op")
    client_rel_id = 11
    secret = Secret(
        tracked_content={"mtls-cert": tls_artifacts.certificate},
        label=f"kafka-client.{client_rel_id}.mtls.secret",
    )
    client_relation = Relation(
        REL_NAME,
        "app",
        id=client_rel_id,
        remote_app_data={
            "topic": "TOPIC",
            "extra-user-roles": "consumer,producer",
            "secret-mtls": secret.id,
        },
    )

    cluster_peer = PeerRelation(
        PEER,
        PEER,
        local_app_data={f"relation-{client_relation.id}": "password", "tls": "enabled"},
        local_unit_data={"certificate": "cert", "ca-cert": "ca"},
    )
    state_in = dataclasses.replace(
        base_state,
        relations=[cluster_peer, client_relation, restart_relation, zk_relation],
        secrets=[secret],
    )

    with (
        patch("workload.KafkaWorkload.read", return_value=["key=value"]),
        patch(
            "events.broker.BrokerOperator.healthy", new_callable=PropertyMock, return_value=True
        ),
        # Model props
        patch("core.models.KafkaCluster.internal_user_credentials"),
        patch(
            "core.models.ZooKeeper.zookeeper_connected",
            new_callable=PropertyMock,
            return_value=True,
        ),
        # TLSManager methods
        patch(
            "managers.tls.TLSManager.get_current_sans",
            return_value={"sans_ip": "ip", "sans_dns": "dns"},
        ),
        patch(
            "managers.tls.TLSManager.build_sans", return_value={"sans_ip": "ip", "sans_dns": "dns"}
        ),
        ctx(ctx.on.relation_changed(client_relation), state_in) as mgr,
    ):
        mock_auth_manager = MagicMock(spec=AuthManager)
        charm = cast(KafkaCharm, mgr.charm)
        charm.broker.auth_manager = mock_auth_manager
        state_out = mgr.run()

    # Then
    assert mock_auth_manager.update_user_acls.call_count == 2
    assert mock_auth_manager.remove_all_user_acls.call_count == 1
    assert f"relation-{client_rel_id}" in mock_auth_manager.remove_all_user_acls.call_args[0]
    assert state_out.app_status == Status.ACTIVE.value.status
