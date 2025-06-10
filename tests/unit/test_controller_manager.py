#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from subprocess import CalledProcessError
from typing import Callable
from unittest.mock import MagicMock

import pytest
from charmlibs import pathops
from src.core.workload import CharmedKafkaPaths, WorkloadBase
from src.literals import BROKER, AuthMap, KRaftUnitStatus
from src.managers.controller import ControllerManager
from tests.unit.data.metadata_quorum_stub import METADATA_QUORUM_STUB


@pytest.fixture()
def fake_workload(tmp_path_factory) -> WorkloadBase:
    workload = MagicMock(spec=WorkloadBase)
    workload.write = lambda content, path: open(path, "w").write(content)
    workload.root = pathops.LocalPath("/")
    workload.paths = CharmedKafkaPaths(BROKER)
    workload.paths.conf_path = tmp_path_factory.mktemp("workload")
    return workload


def _raises_process_error(stderr: str) -> Callable:
    def _exec(*args, **kwargs):
        raise CalledProcessError(returncode=1, cmd="cmd", stderr=stderr)

    return _exec


def test_quorum_status(fake_workload) -> None:
    state = MagicMock()
    state.peer_cluster.bootstrap_controller = "10.10.10.10:9097"
    manager = ControllerManager(state=state, workload=fake_workload)

    fake_workload.run_bin_command.return_value = METADATA_QUORUM_STUB["describe-replication"]
    quorum_status = manager.quorum_status()
    assert len(quorum_status) == 4
    assert quorum_status[0].status == KRaftUnitStatus.LEADER
    assert all(unit.directory_id for unit in quorum_status.values())

    state.kraft_unit_id = 0
    assert manager.is_kraft_leader_or_follower()

    for _id in (100, 101, 1000, 9999):
        state.kraft_unit_id = _id
        assert not manager.is_kraft_leader_or_follower()

    fake_workload.run_bin_command = _raises_process_error(stderr="any-error")
    assert not manager.quorum_status()


def test_add_controller(fake_workload) -> None:
    state = MagicMock()
    state.peer_cluster.bootstrap_controller = "10.10.10.10:9097"
    fake_workload.run_bin_command.return_value = "done"
    manager = ControllerManager(state=state, workload=fake_workload)

    manager.add_controller("10.10.10.10:9097")
    assert fake_workload.run_bin_command.call_args.kwargs["bin_keyword"] == "metadata-quorum"
    _args = " ".join(fake_workload.run_bin_command.call_args.kwargs["bin_args"])
    assert "add-controller" in _args
    assert f"--command-config {fake_workload.paths.conf_path}/server.properties" in _args
    assert "--bootstrap-controller 10.10.10.10:9097" in _args

    # DuplicateVoterException is fine
    fake_workload.run_bin_command = _raises_process_error(
        stderr=METADATA_QUORUM_STUB["duplicate-voter-exception"]
    )
    manager.add_controller("10.10.10.10:9097")

    # Any other exception is also fine, we'll retry on update-status
    fake_workload.run_bin_command = _raises_process_error(
        stderr="org.apache.kafka.common.errors.InvalidConfigurationException"
    )
    manager.add_controller("10.10.10.10:9097")


def test_remove_controller(fake_workload) -> None:
    state = MagicMock()
    state.cluster.bootstrap_controller = "10.10.10.10:9097"
    manager = ControllerManager(state=state, workload=fake_workload)

    fake_workload.run_bin_command.return_value = "done"

    manager.remove_controller(101, "abcdefg")
    assert fake_workload.run_bin_command.call_args.kwargs["bin_keyword"] == "metadata-quorum"
    _args = " ".join(fake_workload.run_bin_command.call_args.kwargs["bin_args"])
    assert "remove-controller" in _args
    assert f"--command-config {fake_workload.paths.conf_path}/server.properties" in _args
    assert "--bootstrap-controller 10.10.10.10:9097" in _args
    assert "--controller-id 101" in _args
    assert "--controller-directory-id abcdefg" in _args

    fake_workload.run_bin_command = _raises_process_error(
        stderr=METADATA_QUORUM_STUB["timeout-exception"]
    )
    manager.remove_controller(101, "directory-id")

    fake_workload.run_bin_command = _raises_process_error(
        stderr="org.apache.kafka.common.errors.InvalidConfigurationException"
    )
    with pytest.raises(CalledProcessError):
        manager.remove_controller(101, "directory-id")


@pytest.mark.parametrize("socket_healthy", [True, False])
def test_listener_health_check(fake_workload, caplog, socket_healthy: bool) -> None:
    caplog.set_level(logging.DEBUG)
    state = MagicMock()
    state.peer_cluster.bootstrap_controller = "10.10.10.10:9097"
    state.brokers = [MagicMock(), MagicMock(), MagicMock()]

    manager = ControllerManager(state=state, workload=fake_workload)

    manager.workload.check_socket.return_value = socket_healthy
    assert (
        manager.listener_health_check("CONTROLLER", AuthMap("SASL_PLAINTEXT", "SCRAM-SHA-512"))
        == socket_healthy
    )
    manager.workload.check_socket.assert_called_once()
    assert manager.workload.check_socket.call_args.args[1] == 9097

    manager.workload.check_socket.reset_mock()
    manager.workload.check_socket.return_value = socket_healthy
    assert (
        manager.listener_health_check(
            "CONTROLLER", AuthMap("SASL_PLAINTEXT", "SCRAM-SHA-512"), all_units=True
        )
        == socket_healthy
    )
    assert manager.workload.check_socket.call_count == 1 if not socket_healthy else 3
