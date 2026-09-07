#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, Mock, PropertyMock, patch

import pytest
from common.single_kernel_kafka.core.literals import ConnectLiterals
from common.single_kernel_kafka.managers.connect import HealthResponse
from ops import EventBase
from ops.testing import Container, Context, PeerRelation, Resource, State

from ..helpers import SUBSTRATE, SUBSTRATE_CLS
from .helpers import ACTIONS, CONFIG, METADATA, ConnectCharm


@pytest.fixture(autouse=True)
def workload(monkeypatch):
    """Workload with completely mocked functionality."""
    monkeypatch.undo()
    monkeypatch.setattr(
        f"single_kernel_kafka.workload.ConnectWorkload{SUBSTRATE_CLS}.exec", Mock()
    )
    monkeypatch.setattr(
        f"single_kernel_kafka.workload.ConnectWorkload{SUBSTRATE_CLS}.installed", True
    )
    monkeypatch.setattr(
        f"single_kernel_kafka.workload.ConnectWorkload{SUBSTRATE_CLS}.write", Mock()
    )
    monkeypatch.setattr(
        f"single_kernel_kafka.workload.ConnectWorkload{SUBSTRATE_CLS}.remove", Mock()
    )
    monkeypatch.setattr(
        f"single_kernel_kafka.workload.ConnectWorkload{SUBSTRATE_CLS}.ls", Mock(return_value=[])
    )
    yield


@pytest.fixture(autouse=True)
def tenacity_wait():
    with patch("tenacity.nap.time") as patched_nap:
        yield patched_nap


@pytest.fixture(scope="module")
def kafka_client_rel():
    return {
        "username": "username",
        "password": "password",
        "tls": "disabled",
        "tls-ca": "disabled",
        "endpoints": "10.10.10.10:9092,10.10.10.11:9092",
    }


@pytest.fixture(scope="module")
def plugin_resource():
    return Resource(
        name=ConnectLiterals.PLUGIN_RESOURCE_KEY,
        path="./tests/unit/connect/resources/FakePlugin.tar",
    )


class MockAcquireLock(EventBase):
    def __init__(self, handle, callback_override: str | None = None):
        super().__init__(handle)
        self.callback_override = "_restart_callback"

    def snapshot(self):
        """Snapshot of lock event."""
        return {"callback_override": self.callback_override}

    def restore(self, snapshot):
        """Restores lock event."""
        self.callback_override = snapshot["callback_override"]


@pytest.fixture
def restart_rel(monkeypatch):
    monkeypatch.setattr("charms.rolling_ops.v0.rollingops.AcquireLock", MockAcquireLock)

    return PeerRelation("restart", "rolling_op")


@pytest.fixture(scope="function")
def active_service():
    mock_response = MagicMock()
    mock_response.json.return_value = {}

    with (
        patch(
            "single_kernel_kafka.managers.connect.ConnectManager.healthy",
            new_callable=PropertyMock,
            return_value=HealthResponse(status_code=200),
        ) as patched_service,
        patch(
            "single_kernel_kafka.managers.connect.ConnectManager._request",
            return_value=mock_response,
        ),
    ):
        yield patched_service


@pytest.fixture(scope="function")
def dead_service():
    mock_response = MagicMock()
    mock_response.json.return_value = {}

    with (
        patch(
            "single_kernel_kafka.managers.connect.ConnectManager.healthy",
            new_callable=PropertyMock,
            return_value=HealthResponse(status_code=503),
        ) as patched_service,
        patch(
            "single_kernel_kafka.managers.connect.ConnectManager._request",
            return_value=mock_response,
        ),
    ):
        yield patched_service


@pytest.fixture()
def base_state(restart_rel):
    peer_rel = PeerRelation(ConnectLiterals.PEER_REL, ConnectLiterals.PEER_REL)
    if SUBSTRATE == "k8s":
        state = State(
            leader=True,
            containers=[Container(name=ConnectCharm.container_name, can_connect=True)],
            relations=[restart_rel, peer_rel],
        )
    else:
        state = State(leader=True, relations=[restart_rel, peer_rel])

    return state


@pytest.fixture()
def ctx() -> Context:
    ctx = Context(ConnectCharm, meta=METADATA, config=CONFIG, actions=ACTIONS, unit_id=0)
    return ctx
