#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
import json
import logging
import re
from pathlib import Path
from typing import cast
from unittest.mock import PropertyMock, patch

import pytest
import yaml
from ops import ActiveStatus
from ops.testing import ActionFailed, Container, Context, PeerRelation, Relation, State

from charm import KafkaCharm
from literals import (
    BALANCER_TOPICS,
    BALANCER_WEBSERVER_USER,
    CONTAINER,
    PEER,
    SUBSTRATE,
    ZK,
    Status,
)
from managers.balancer import CruiseControlClient

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


class MockResponse:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code

    def json(self):
        return self.content

    def __dict__(self):
        """Dict representation of content."""
        return self.content


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


def test_client_get_args(client: CruiseControlClient):
    with patch("managers.balancer.requests.get") as patched_get:
        client.get("silmaril")

        _, kwargs = patched_get.call_args

        assert kwargs["params"]["json"]
        assert kwargs["params"]["json"] == "True"

        assert kwargs["auth"]
        assert kwargs["auth"] == ("Beren", "Luthien")


def test_client_post_args(client: CruiseControlClient):
    with patch("managers.balancer.requests.post") as patched_post:
        client.post("silmaril")

        _, kwargs = patched_post.call_args

        assert kwargs["params"]["json"]
        assert kwargs["params"]["dryrun"]
        assert kwargs["auth"]

        assert kwargs["params"]["json"] == "True"
        assert kwargs["params"]["dryrun"] == "False"
        assert kwargs["auth"] == ("Beren", "Luthien")


def test_client_get_task_status(client: CruiseControlClient, user_tasks: dict):
    with patch("managers.balancer.requests.get", return_value=MockResponse(user_tasks)):
        assert (
            client.get_task_status(user_task_id="e4256bcb-93f7-4290-ab11-804a665bf011")
            == "Completed"
        )


def test_client_monitoring(client: CruiseControlClient, state: dict):
    with patch("managers.balancer.requests.get", return_value=MockResponse(state)):
        assert client.monitoring


def test_client_executing(client: CruiseControlClient, state: dict):
    with patch("managers.balancer.requests.get", return_value=MockResponse(state)):
        assert not client.executing


def test_client_ready(client: CruiseControlClient, state: dict):
    with patch("managers.balancer.requests.get", return_value=MockResponse(state)):
        assert client.ready

    not_ready_state = state
    not_ready_state["MonitorState"]["numMonitoredWindows"] = 0  # aka not ready

    with patch("managers.balancer.requests.get", return_value=MockResponse(not_ready_state)):
        assert not client.ready


def test_balancer_manager_create_internal_topics(
    ctx_broker_and_balancer: Context, base_state: State
) -> None:
    # Given
    ctx = ctx_broker_and_balancer
    state_in = base_state

    # When
    with (
        patch("core.models.PeerCluster.broker_uris", new_callable=PropertyMock, return_value=""),
        patch(
            "workload.BalancerWorkload.run_bin_command",
            new_callable=None,
            return_value=BALANCER_TOPICS[0],  # pretend it exists already
        ) as patched_run,
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)
        charm.balancer.balancer_manager.create_internal_topics()

    # Then

    assert len(patched_run.call_args_list) == 5  # checks for existence 3 times, creates 2 times

    list_counter = 0
    for args, _ in patched_run.call_args_list:
        all_flags = "".join(args[1])

        if "list" in all_flags:
            list_counter += 1

        # only created needed topics
        if "create" in all_flags:
            assert any((topic in all_flags) for topic in BALANCER_TOPICS)
            assert BALANCER_TOPICS[0] not in all_flags

    assert list_counter == len(BALANCER_TOPICS)  # checked for existence of all balancer topics


@pytest.mark.parametrize("leader", [False, True])
@pytest.mark.parametrize("monitoring", [True, False])
@pytest.mark.parametrize("executing", [True, False])
@pytest.mark.parametrize("ready", [True, False])
@pytest.mark.parametrize("status", [200, 404])
def test_balancer_manager_rebalance_full(
    ctx_broker_and_balancer: Context,
    base_state: State,
    proposal: dict,
    leader: bool,
    monitoring: bool,
    executing: bool,
    ready: bool,
    status: int,
) -> None:
    # Given
    ctx = ctx_broker_and_balancer
    state_in = dataclasses.replace(base_state, leader=leader)
    payload = {"mode": "full", "dryrun": True}

    # When
    with (
        patch(
            "managers.balancer.CruiseControlClient.monitoring",
            new_callable=PropertyMock,
            return_value=monitoring,
        ),
        patch(
            "managers.balancer.CruiseControlClient.executing",
            new_callable=PropertyMock,
            return_value=not executing,
        ),
        patch(
            "managers.balancer.CruiseControlClient.ready",
            new_callable=PropertyMock,
            return_value=ready,
        ),
        patch(
            "managers.balancer.BalancerManager.rebalance",
            new_callable=None,
            return_value=(MockResponse(content=proposal, status_code=status), "foo"),
        ),
        patch(
            "managers.balancer.BalancerManager.wait_for_task",
            new_callable=None,
        ) as patched_wait_for_task,
    ):

        if not all([leader, monitoring, executing, ready, status == 200]):
            with pytest.raises(ActionFailed):
                ctx.run(ctx.on.action("rebalance", params=payload), state_in)
        else:
            ctx.run(ctx.on.action("rebalance", params=payload), state_in)
            assert patched_wait_for_task.call_count


@pytest.mark.parametrize("mode", ["add", "remove"])
@pytest.mark.parametrize("brokerid", [None, 0])
def test_rebalance_add_remove_broker_id_length(
    ctx_broker_and_balancer: Context,
    base_state: State,
    proposal: dict,
    mode: str,
    brokerid: int | None,
):
    # Given
    ctx = ctx_broker_and_balancer
    state_in = base_state

    payload = {"mode": mode, "dryrun": True}
    payload = payload | {"brokerid": brokerid} if brokerid is not None else payload

    # When
    with (
        patch(
            "managers.balancer.CruiseControlClient.monitoring",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch(
            "managers.balancer.CruiseControlClient.executing",
            new_callable=PropertyMock,
            return_value=not True,
        ),
        patch(
            "managers.balancer.CruiseControlClient.ready",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch(
            "managers.balancer.BalancerManager.rebalance",
            new_callable=None,
            return_value=(MockResponse(content=proposal, status_code=200), "foo"),
        ),
        patch(
            "managers.balancer.BalancerManager.wait_for_task",
            new_callable=None,
        ) as patched_wait_for_task,
    ):

        if brokerid is None:
            with pytest.raises(ActionFailed):
                ctx.run(ctx.on.action("rebalance", params=payload), state_in)

        else:
            ctx.run(ctx.on.action("rebalance", params=payload), state_in)

            # Then
            assert patched_wait_for_task.call_count


def test_rebalance_broker_id_not_found(
    ctx_broker_and_balancer: Context, base_state: State
) -> None:
    # Given
    ctx = ctx_broker_and_balancer
    state_in = base_state
    payload = {"mode": "add", "dryrun": True, "brokerid": 999}  # only one unit in the state

    # When
    with (
        patch(
            "managers.balancer.CruiseControlClient.monitoring",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch(
            "managers.balancer.CruiseControlClient.executing",
            new_callable=PropertyMock,
            return_value=not True,
        ),
        patch(
            "managers.balancer.CruiseControlClient.ready",
            new_callable=PropertyMock,
            return_value=True,
        ),
    ):

        with pytest.raises(ActionFailed):
            ctx.run(ctx.on.action("rebalance", params=payload), state_in)


def test_balancer_manager_clean_results(
    ctx_broker_and_balancer: Context, base_state: State, proposal: dict
) -> None:
    # Given
    ctx = ctx_broker_and_balancer
    state_in = base_state

    def _check_cleaned_results(value) -> bool:
        if isinstance(value, list):
            for item in value:
                assert not isinstance(item, dict)

        if isinstance(value, dict):
            for k, v in value.items():
                assert k.islower()
                assert _check_cleaned_results(v)

        return True

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)
        cleaned_results = charm.balancer.balancer_manager.clean_results(value=proposal)

    # Then
    assert _check_cleaned_results(cleaned_results)
