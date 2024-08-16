#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
import yaml
from ops.testing import Harness

from charm import KafkaCharm
from literals import BALANCER_TOPICS, CHARM_KEY, CONTAINER, SUBSTRATE
from managers.balancer import CruiseControlClient

logger = logging.getLogger(__name__)

CONFIG = str(yaml.safe_load(Path("./config.yaml").read_text()))
ACTIONS = str(yaml.safe_load(Path("./actions.yaml").read_text()))
METADATA = str(yaml.safe_load(Path("./metadata.yaml").read_text()))


class MockResponse:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code

    def json(self):
        return self.content

    def __dict__(self):
        """Dict representation of content."""
        return self.content


@pytest.fixture
def harness():
    harness = Harness(KafkaCharm, meta=METADATA)

    if SUBSTRATE == "k8s":
        harness.set_can_connect(CONTAINER, True)

    harness.add_relation("restart", CHARM_KEY)
    harness._update_config(
        {
            "log_retention_ms": "-1",
            "compression_type": "producer",
            "roles": "broker,balancer",
        }
    )
    harness.set_leader(True)

    harness.begin()
    return harness


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


def test_balancer_manager_create_internal_topics(harness: Harness[KafkaCharm]):
    with (
        patch("core.models.PeerCluster.broker_uris", new_callable=PropertyMock, return_value=""),
        patch(
            "workload.BalancerWorkload.run_bin_command",
            new_callable=None,
            return_value=BALANCER_TOPICS[0],  # pretend it exists already
        ) as patched_run,
    ):
        harness.charm.balancer.balancer_manager.create_internal_topics()

        assert (
            len(patched_run.call_args_list) == 5
        )  # checks for existence 3 times, creates 2 times

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


@pytest.mark.parametrize("leader", [True, False])
@pytest.mark.parametrize("monitoring", [True, False])
@pytest.mark.parametrize("executing", [True, False])
@pytest.mark.parametrize("ready", [True, False])
@pytest.mark.parametrize("status", [200, 404])
def test_balancer_manager_rebalance_full(
    harness: Harness[KafkaCharm],
    proposal: dict,
    leader: bool,
    monitoring: bool,
    executing: bool,
    ready: bool,
    status: int,
):
    mock_event = MagicMock()
    mock_event.params = {"mode": "full", "dryrun": True}

    with (
        harness.hooks_disabled(),
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
        harness.set_leader(leader)
        harness.charm.balancer.rebalance(mock_event)

        if not all([leader, monitoring, executing, ready, status == 200]):
            assert mock_event._mock_children.get("fail")  # event.fail was called
        else:
            assert patched_wait_for_task.call_count
            assert mock_event._mock_children.get("set_results")  # event.set_results was called


@pytest.mark.parametrize("mode", ["add", "remove"])
@pytest.mark.parametrize("brokerid", [None, 0])
def test_rebalance_add_remove_broker_id_length(
    harness: Harness[KafkaCharm], proposal: dict, mode: str, brokerid: int | None
):
    mock_event = MagicMock()
    payload = {"mode": mode, "dryrun": True}
    payload = payload | {"brokerid": brokerid} if brokerid is not None else payload
    mock_event.params = payload

    with (
        harness.hooks_disabled(),
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
        harness.set_leader(True)

        # When
        harness.charm.balancer.rebalance(mock_event)

        # Then
        if brokerid is None:
            assert mock_event._mock_children.get("fail")  # event.fail was called
        else:
            assert patched_wait_for_task.call_count
            assert mock_event._mock_children.get("set_results")  # event.set_results was called


def test_rebalance_broker_id_not_found(harness: Harness[KafkaCharm]):
    mock_event = MagicMock()
    payload = {"mode": "add", "dryrun": True, "brokerid": 999}
    mock_event.params = payload

    with (
        harness.hooks_disabled(),
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
        harness.set_leader(True)

        # When
        harness.charm.balancer.rebalance(mock_event)

        # Then
        assert mock_event._mock_children.get("fail")  # event.fail was called


def test_balancer_manager_clean_results(harness: Harness[KafkaCharm], proposal: dict):
    cleaned_results = harness.charm.balancer.balancer_manager.clean_results(value=proposal)

    def _check_cleaned_results(value) -> bool:
        if isinstance(value, list):
            for item in value:
                assert not isinstance(item, dict)

        if isinstance(value, dict):
            for k, v in value.items():
                assert k.islower()
                assert _check_cleaned_results(v)

        return True

    assert _check_cleaned_results(cleaned_results)
