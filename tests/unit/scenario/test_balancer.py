#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
import json
import logging
import re
from pathlib import Path
from unittest.mock import PropertyMock, patch

import pytest
import yaml
from ops import ActiveStatus
from scenario import Container, Context, PeerRelation, Relation, State

from charm import KafkaCharm
from literals import (
    BALANCER_WEBSERVER_USER,
    CONTAINER,
    PEER,
    SUBSTRATE,
    ZK,
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


@pytest.fixture()
def base_state():

    if SUBSTRATE == "k8s":
        state = State(leader=True, containers=[Container(name=CONTAINER, can_connect=True)])

    else:
        state = State(leader=True)

    return state


@pytest.fixture()
def ctx_balancer_only(charm_configuration: dict) -> Context:
    charm_configuration["options"]["roles"]["default"] = "balancer"
    ctx = Context(
        KafkaCharm, meta=METADATA, config=charm_configuration, actions=ACTIONS, unit_id=0
    )
    return ctx


@pytest.fixture()
def ctx_broker_and_balancer(charm_configuration: dict) -> Context:
    charm_configuration["options"]["roles"]["default"] = "broker,balancer"
    ctx = Context(
        KafkaCharm, meta=METADATA, config=charm_configuration, actions=ACTIONS, unit_id=0
    )
    return ctx


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="snap not used on K8s")
def test_install_blocks_snap_install_failure(
    ctx_balancer_only: Context, base_state: State
) -> None:
    # Given
    ctx = ctx_balancer_only
    state_in = base_state

    # When
    with patch("workload.Workload.install", return_value=False), patch("workload.Workload.write"):
        state_out = ctx.run(ctx.on.install(), state_in)

    # Then
    assert state_out.unit_status == Status.SNAP_NOT_INSTALLED.value.status


@patch("workload.Workload.restart")
@patch("workload.Workload.start")
def test_stop_workload_if_not_leader(
    patched_start, patched_restart, ctx_balancer_only: Context, base_state: State
) -> None:
    # Given
    ctx = ctx_balancer_only
    state_in = dataclasses.replace(base_state, leader=False)

    # When
    ctx.run(ctx.on.start(), state_in)

    # Then
    assert not patched_start.called
    assert not patched_restart.called


def test_stop_workload_if_role_not_present(ctx_balancer_only: Context, base_state: State) -> None:
    # Given
    ctx = ctx_balancer_only
    state_in = dataclasses.replace(base_state, config={"roles": "broker"})

    # When
    with (
        patch("workload.BalancerWorkload.active", return_value=True),
        patch("workload.BalancerWorkload.stop") as patched_stopped,
    ):
        ctx.run(ctx.on.config_changed(), state_in)

    # Then
    patched_stopped.assert_called_once()


def test_ready_to_start_maintenance_no_peer_relation(
    ctx_balancer_only: Context, base_state: State
) -> None:
    # Given
    ctx = ctx_balancer_only
    state_in = base_state

    # When
    state_out = ctx.run(ctx.on.start(), state_in)

    # Then
    assert state_out.unit_status == Status.NO_PEER_RELATION.value.status


def test_ready_to_start_no_peer_cluster(ctx_balancer_only: Context, base_state: State) -> None:
    """Balancer only, need a peer cluster relation."""
    # Given
    ctx = ctx_balancer_only
    cluster_peer = PeerRelation(PEER, PEER)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer])

    # When
    state_out = ctx.run(ctx.on.start(), state_in)

    # Then
    assert state_out.unit_status == Status.NO_PEER_CLUSTER_RELATION.value.status


def test_ready_to_start_no_zk_data(ctx_broker_and_balancer: Context, base_state: State) -> None:
    # Given
    ctx = ctx_broker_and_balancer
    cluster_peer = PeerRelation(PEER, PEER)
    relation = Relation(
        interface=ZK,
        endpoint=ZK,
        remote_app_name=ZK,
    )
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, relation])

    # When
    state_out = ctx.run(ctx.on.start(), state_in)

    # Then
    assert state_out.unit_status == Status.ZK_NO_DATA.value.status


def test_ready_to_start_no_broker_data(
    ctx_broker_and_balancer: Context,
    base_state: State,
    zk_data: dict[str, str],
    passwords_data: dict[str, str],
) -> None:
    # Given
    ctx = ctx_broker_and_balancer
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data)
    relation = Relation(interface=ZK, endpoint=ZK, remote_app_name=ZK, remote_app_data=zk_data)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, relation])

    # When
    state_out = ctx.run(ctx.on.start(), state_in)

    # Then
    assert state_out.unit_status == Status.NO_BROKER_DATA.value.status


def test_ready_to_start_ok(
    ctx_broker_and_balancer: Context,
    base_state: State,
    zk_data: dict[str, str],
    passwords_data: dict[str, str],
) -> None:
    # Given
    ctx = ctx_broker_and_balancer
    cluster_peer = PeerRelation(
        PEER,
        local_app_data=passwords_data,
        peers_data={
            i: {
                "cores": "8",
                "storages": json.dumps(
                    {f"/var/snap/charmed-kafka/common/var/lib/kafka/data/{i}": "10240"}
                ),
            }
            for i in range(1, 3)
        },
        local_unit_data={
            "cores": "8",
            "storages": json.dumps(
                {f"/var/snap/charmed-kafka/common/var/lib/kafka/data/{0}": "10240"}
            ),
        },
    )
    restart_peer = PeerRelation("restart", "restart")
    relation = Relation(interface=ZK, endpoint=ZK, remote_app_name=ZK)
    state_in = dataclasses.replace(
        base_state, relations=[cluster_peer, restart_peer, relation], planned_units=3
    )

    # When
    with (
        patch("workload.BalancerWorkload.write") as patched_writer,
        patch("workload.BalancerWorkload.read"),
        patch(
            "json.loads",
            return_value={"brokerCapacities": [{}, {}, {}]},
        ),
        patch(
            "core.cluster.ClusterState.broker_capacities",
            new_callable=PropertyMock,
            return_value={"brokerCapacities": [{}, {}, {}]},
        ),
        patch("workload.KafkaWorkload.read"),
        patch("workload.BalancerWorkload.exec"),
        patch("workload.BalancerWorkload.restart"),
        patch("workload.KafkaWorkload.start"),
        patch("workload.BalancerWorkload.active", return_value=True),
        patch("workload.KafkaWorkload.active", return_value=True),
        patch("core.models.ZooKeeper.broker_active", return_value=True),
        patch(
            "core.models.ZooKeeper.zookeeper_connected",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch(
            "core.models.PeerCluster.broker_connected",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch(
            "managers.config.ConfigManager.server_properties",
            new_callable=PropertyMock,
            return_value=[],
        ),
        patch(
            "managers.config.BalancerConfigManager.cruise_control_properties",
            new_callable=PropertyMock,
            return_value=[],
        ),
        patch(
            "managers.config.ConfigManager.jaas_config", new_callable=PropertyMock, return_value=""
        ),
        patch(
            "managers.config.BalancerConfigManager.jaas_config",
            new_callable=PropertyMock,
            return_value="",
        ),
        patch("health.KafkaHealth.machine_configured", return_value=True),
        patch("charms.operator_libs_linux.v1.snap.SnapCache"),  # specific VM, works fine on k8s
    ):
        state_out = ctx.run(ctx.on.start(), state_in)

    # Then
    assert state_out.unit_status == ActiveStatus()
    # Credentials written to file
    assert re.match(
        rf"{BALANCER_WEBSERVER_USER}: \w+,ADMIN",
        patched_writer.call_args_list[-1].kwargs["content"],
    )
