#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
import json
import logging
import re
from typing import cast
from unittest.mock import PropertyMock, patch

import pytest
from common.single_kernel_kafka.core.literals import (
    BALANCER_TOPICS,
    BALANCER_WEBSERVER_USER,
    CONTAINER,
    PEER,
    Status,
)
from common.single_kernel_kafka.managers.balancer import CruiseControlClient
from ops import ActiveStatus
from ops.testing import ActionFailed, Container, Context, PeerRelation, State
from tests.unit.helpers import (
    ACTIONS,
    CONFIG,
    METADATA,
    SUBSTRATE,
    SUBSTRATE_CLS,
    KafkaCharm,
    generate_tls_artifacts,
)

pytestmark = pytest.mark.balancer

logger = logging.getLogger(__name__)


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
    charm_configuration["options"]["roles"]["default"] = "controller,balancer"
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
    with (
        patch(f"single_kernel_kafka.workload.Workload{SUBSTRATE_CLS}.install", return_value=False),
        patch(f"single_kernel_kafka.workload.Workload{SUBSTRATE_CLS}.write"),
    ):
        state_out = ctx.run(ctx.on.install(), state_in)

    # Then
    assert state_out.unit_status == Status.SNAP_NOT_INSTALLED.value.status


@patch(f"single_kernel_kafka.workload.Workload{SUBSTRATE_CLS}.restart")
@patch(f"single_kernel_kafka.workload.Workload{SUBSTRATE_CLS}.start")
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
        patch(
            f"single_kernel_kafka.workload.BalancerWorkload{SUBSTRATE_CLS}.active",
            return_value=True,
        ),
        patch(
            f"single_kernel_kafka.workload.BalancerWorkload{SUBSTRATE_CLS}.stop"
        ) as patched_stopped,
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


def test_ready_to_start_no_controller(ctx_broker_and_balancer: Context, base_state: State) -> None:
    # Given
    ctx = ctx_broker_and_balancer
    cluster_peer = PeerRelation(PEER, PEER)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer])

    # When
    state_out = ctx.run(ctx.on.start(), state_in)

    # Then
    assert state_out.unit_status == Status.MISSING_MODE.value.status


def test_ready_to_start_ok(
    ctx_broker_and_balancer: Context,
    base_state: State,
    kraft_data: dict[str, str],
    passwords_data: dict[str, str],
) -> None:
    # Given
    ctx = ctx_broker_and_balancer
    tls_data = generate_tls_artifacts()
    cluster_peer = PeerRelation(
        PEER,
        local_app_data=passwords_data | kraft_data | {"controller-password": "password"},
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
            "peer-certificate": tls_data.certificate,
            "peer-ca-cert": tls_data.ca,
        },
    )
    restart_peer = PeerRelation("restart", "restart")
    state_in = dataclasses.replace(
        base_state,
        relations=[cluster_peer, restart_peer],
        planned_units=3,
        config={"roles": "broker,controller,balancer"},
    )

    # When
    with (
        patch(
            "single_kernel_kafka.managers.balancer.BalancerManager.get_partition_assignment",
            return_value={},
        ),
        patch(
            f"single_kernel_kafka.workload.BalancerWorkload{SUBSTRATE_CLS}.write"
        ) as patched_writer,
        patch(
            "single_kernel_kafka.core.cluster.KafkaContext.broker_capacities",
            new_callable=PropertyMock,
            return_value={"brokerCapacities": [{}, {}, {}]},
        ),
        patch(
            "single_kernel_kafka.managers.balancer.BalancerManager.config_change_detected",
            return_value=False,
        ),
        patch(
            "single_kernel_kafka.core.cluster.KafkaContext.broker_capacities",
            new_callable=PropertyMock,
            return_value={"brokerCapacities": [{}, {}, {}]},
        ),
        patch(f"single_kernel_kafka.workload.KafkaWorkload{SUBSTRATE_CLS}.read"),
        patch(f"single_kernel_kafka.workload.BalancerWorkload{SUBSTRATE_CLS}.restart"),
        patch(f"single_kernel_kafka.workload.KafkaWorkload{SUBSTRATE_CLS}.start"),
        patch(
            f"single_kernel_kafka.workload.BalancerWorkload{SUBSTRATE_CLS}.active",
            return_value=True,
        ),
        patch(
            f"single_kernel_kafka.workload.KafkaWorkload{SUBSTRATE_CLS}.active", return_value=True
        ),
        patch(
            "single_kernel_kafka.core.models.PeerCluster.broker_connected",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch(
            "single_kernel_kafka.managers.config.ConfigManager.server_properties",
            new_callable=PropertyMock,
            return_value=[],
        ),
        patch(
            "single_kernel_kafka.managers.config.BalancerConfigManager.cruise_control_properties",
            new_callable=PropertyMock,
            return_value=[],
        ),
        patch(
            "single_kernel_kafka.managers.tls.TLSManager.build_sans",
            return_value={"sans_ip": ["10.10.10.10"], "sans_dns": ["dns"]},
        ),
        patch(
            "single_kernel_kafka.managers.tls.TLSManager.get_current_sans",
            return_value={"sans_ip": ["10.10.10.10"], "sans_dns": ["dns"]},
        ),
        patch("single_kernel_kafka.managers.tls.TLSManager.configure"),
        patch("single_kernel_kafka.health.KafkaHealth.machine_configured", return_value=True),
        patch("charmlibs.snap.SnapCache"),  # specific VM, works fine on k8s
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
    with patch("single_kernel_kafka.managers.balancer.requests.get") as patched_get:
        client.get("silmaril")

        _, kwargs = patched_get.call_args

        assert kwargs["params"]["json"]
        assert kwargs["params"]["json"] == "True"

        assert kwargs["auth"]
        assert kwargs["auth"] == ("Beren", "Luthien")


def test_client_post_args(client: CruiseControlClient):
    with patch("single_kernel_kafka.managers.balancer.requests.post") as patched_post:
        client.post("silmaril")

        _, kwargs = patched_post.call_args

        assert kwargs["params"]["json"]
        assert kwargs["params"]["dryrun"]
        assert kwargs["auth"]

        assert kwargs["params"]["json"] == "True"
        assert kwargs["params"]["dryrun"] == "False"
        assert kwargs["auth"] == ("Beren", "Luthien")


def test_client_get_task_status(client: CruiseControlClient, user_tasks: dict):
    with patch(
        "single_kernel_kafka.managers.balancer.requests.get", return_value=MockResponse(user_tasks)
    ):
        assert (
            client.get_task_status(user_task_id="e4256bcb-93f7-4290-ab11-804a665bf011")
            == "Completed"
        )


def test_client_monitoring(client: CruiseControlClient, state: dict):
    with patch(
        "single_kernel_kafka.managers.balancer.requests.get", return_value=MockResponse(state)
    ):
        assert client.monitoring


def test_client_executing(client: CruiseControlClient, state: dict):
    with patch(
        "single_kernel_kafka.managers.balancer.requests.get", return_value=MockResponse(state)
    ):
        assert not client.executing


def test_client_ready(client: CruiseControlClient, state: dict):
    with patch(
        "single_kernel_kafka.managers.balancer.requests.get", return_value=MockResponse(state)
    ):
        assert client.ready

    not_ready_state = state
    not_ready_state["MonitorState"]["numMonitoredWindows"] = 0  # aka not ready

    with patch(
        "single_kernel_kafka.managers.balancer.requests.get",
        return_value=MockResponse(not_ready_state),
    ):
        assert not client.ready


def test_balancer_manager_create_internal_topics(
    ctx_broker_and_balancer: Context, base_state: State
) -> None:
    # Given
    ctx = ctx_broker_and_balancer
    state_in = base_state

    # When
    with (
        patch(
            "single_kernel_kafka.core.models.PeerCluster.broker_uris",
            new_callable=PropertyMock,
            return_value="",
        ),
        patch(
            f"single_kernel_kafka.workload.BalancerWorkload{SUBSTRATE_CLS}.run_bin_command",
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


@pytest.mark.parametrize("balancer", [True, False])
@pytest.mark.parametrize("leader", [False, True])
@pytest.mark.parametrize("monitoring", [True, False])
@pytest.mark.parametrize("executing", [True, False])
@pytest.mark.parametrize("ready", [True, False])
@pytest.mark.parametrize("status", [200, 404])
def test_balancer_manager_rebalance_full(
    ctx_broker_and_balancer: Context,
    base_state: State,
    proposal: dict,
    balancer: bool,
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
            "single_kernel_kafka.core.cluster.KafkaContext.runs_balancer",
            new_callable=PropertyMock,
            return_value=balancer,
        ),
        patch(
            "single_kernel_kafka.managers.balancer.CruiseControlClient.monitoring",
            new_callable=PropertyMock,
            return_value=monitoring,
        ),
        patch(
            "single_kernel_kafka.managers.balancer.CruiseControlClient.executing",
            new_callable=PropertyMock,
            return_value=not executing,
        ),
        patch(
            "single_kernel_kafka.managers.balancer.CruiseControlClient.ready",
            new_callable=PropertyMock,
            return_value=ready,
        ),
        patch(
            "single_kernel_kafka.managers.balancer.BalancerManager.rebalance",
            new_callable=None,
            return_value=(MockResponse(content=proposal, status_code=status), "foo"),
        ),
        patch(
            "single_kernel_kafka.managers.balancer.BalancerManager.wait_for_task",
            new_callable=None,
        ) as patched_wait_for_task,
    ):

        if not all([balancer, leader, monitoring, executing, ready, status == 200]):
            with pytest.raises(ActionFailed):
                ctx.run(ctx.on.action("rebalance", params=payload), state_in)
        else:
            ctx.run(ctx.on.action("rebalance", params=payload), state_in)
            assert patched_wait_for_task.call_count


@pytest.mark.parametrize("mode", ["add", "remove"])
@pytest.mark.parametrize("brokerid", [None, 100])
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
            "single_kernel_kafka.managers.balancer.CruiseControlClient.monitoring",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch(
            "single_kernel_kafka.managers.balancer.CruiseControlClient.executing",
            new_callable=PropertyMock,
            return_value=not True,
        ),
        patch(
            "single_kernel_kafka.managers.balancer.CruiseControlClient.ready",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch(
            "single_kernel_kafka.managers.balancer.BalancerManager.rebalance",
            new_callable=None,
            return_value=(MockResponse(content=proposal, status_code=200), "foo"),
        ),
        patch(
            "single_kernel_kafka.managers.balancer.BalancerManager.wait_for_task",
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
            "single_kernel_kafka.managers.balancer.CruiseControlClient.monitoring",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch(
            "single_kernel_kafka.managers.balancer.CruiseControlClient.executing",
            new_callable=PropertyMock,
            return_value=not True,
        ),
        patch(
            "single_kernel_kafka.managers.balancer.CruiseControlClient.ready",
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
