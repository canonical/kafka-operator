#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import json
from collections import defaultdict
from unittest.mock import Mock, PropertyMock, patch

import pytest
from ops import JujuVersion
from src.literals import INTERNAL_USERS, SNAP_NAME, SUBSTRATE
from tests.unit.helpers import TLSArtifacts, generate_tls_artifacts

from managers.balancer import CruiseControlClient


@pytest.fixture(scope="module")
def zk_data() -> dict[str, str]:
    return {
        "username": "glorfindel",
        "password": "mellon",
        "endpoints": "10.10.10.10",
        "database": "/kafka",
        "chroot": "/kafka",
        "uris": "10.10.10.10:2181",
        "tls": "disabled",
    }


@pytest.fixture(scope="module")
def passwords_data() -> dict[str, str]:
    return {f"{user}-password": "mellon" for user in INTERNAL_USERS}


@pytest.fixture(autouse=True)
def patched_pebble_restart(mocker):
    mocker.patch("ops.model.Container.restart")


@pytest.fixture(autouse=True)
def patched_etc_environment():
    with patch("managers.config.ConfigManager.set_environment") as etc_env:
        yield etc_env


@pytest.fixture(autouse=True)
def patched_workload(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    monkeypatch.setattr("workload.Workload.active", lambda _: True)
    monkeypatch.setattr("workload.Workload.write", lambda _, content, path: None)
    monkeypatch.setattr("workload.Workload.read", lambda _, path: [])


@pytest.fixture(autouse=True)
def patched_sysctl_config():
    if SUBSTRATE == "vm":
        with patch("charm.sysctl.Config.configure") as sysctl_config:
            yield sysctl_config
    else:
        yield


@pytest.fixture(autouse=True)
def patched_exec():
    with patch("workload.KafkaWorkload.exec") as patched_exec:
        yield patched_exec


@pytest.fixture()
def patched_health_machine_configured():
    if SUBSTRATE == "vm":
        with patch(
            "health.KafkaHealth.machine_configured", return_value=True
        ) as machine_configured:
            yield machine_configured
    else:
        yield


@pytest.fixture(autouse=True)
def juju_has_secrets(mocker):
    """Using Juju3 we should always have secrets available."""
    mocker.patch.object(JujuVersion, "has_secrets", new_callable=PropertyMock).return_value = True


@pytest.fixture
def client() -> CruiseControlClient:
    return CruiseControlClient("Beren", "Luthien")


@pytest.fixture(scope="function")
def state() -> dict:
    with open("tests/unit/data/state.json") as f:
        content = f.read()

    return json.loads(content)


@pytest.fixture(scope="function")
def kafka_cluster_state() -> dict:
    with open("tests/unit/data/kafka_cluster_state.json") as f:
        content = f.read()

    return json.loads(content)


@pytest.fixture(scope="function")
def proposal() -> dict:
    with open("tests/unit/data/proposal.json") as f:
        content = f.read()

    return json.loads(content)


@pytest.fixture(scope="function")
def user_tasks() -> dict:
    with open("tests/unit/data/user_tasks.json") as f:
        content = f.read()

    return json.loads(content)


@pytest.fixture(autouse=True)
def patched_node_ip():
    if SUBSTRATE == "k8s":
        with patch(
            "core.models.KafkaBroker.node_ip", new_callable=PropertyMock, return_value="1234"
        ) as patched_node_ip:
            yield patched_node_ip
    else:
        yield


@pytest.fixture(autouse=True)
def patched_node_port():
    if SUBSTRATE == "k8s":
        with patch(
            "managers.k8s.K8sManager.get_listener_nodeport",
            return_value=20000,
        ) as patched_node_port:
            yield patched_node_port
    else:
        yield


@pytest.fixture(autouse=True)
def patched_snap(monkeypatch):
    cache = Mock()
    snap_mock = Mock()
    snap_mock.services = defaultdict(default_factory=lambda _: {"active": True})
    cache.return_value = {SNAP_NAME: snap_mock}
    with monkeypatch.context() as m:
        m.setattr("charms.operator_libs_linux.v2.snap.SnapCache", cache)
        yield


@pytest.fixture
def tls_artifacts(request: pytest.FixtureRequest) -> TLSArtifacts:
    return generate_tls_artifacts(with_intermediate=bool(request.param))
