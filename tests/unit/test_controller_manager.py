#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

from subprocess import CalledProcessError
from typing import Callable
from unittest.mock import MagicMock

import pytest
from charmlibs import pathops
from src.core.workload import CharmedKafkaPaths, WorkloadBase
from src.literals import BROKER, KRaftQuorumInfo, KRaftUnitStatus
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


def _is_leader_or_follower(unit_info: KRaftQuorumInfo | None):
    if not unit_info:
        return False

    return unit_info.status in (KRaftUnitStatus.LEADER, KRaftUnitStatus.FOLLOWER)


def test_quorum_status(fake_workload) -> None:
    state = MagicMock()
    state.peer_cluster.bootstrap_controller = "10.10.10.10:9097"
    manager = ControllerManager(state=state, workload=fake_workload)

    fake_workload.run_bin_command.return_value = METADATA_QUORUM_STUB["describe-replication"]
    quorum_status = manager.quorum_status()
    assert len(quorum_status) == 4
    assert quorum_status[0].status == KRaftUnitStatus.LEADER
    assert all(unit.directory_id for unit in quorum_status.values())

    assert _is_leader_or_follower(manager.quorum_status().get(0))

    for _id in (100, 101, 1000, 9999):
        assert not _is_leader_or_follower(manager.quorum_status().get(_id))

    fake_workload.run_bin_command = _raises_process_error(stderr="any-error")
    assert not manager.quorum_status()


def test_broker_active(fake_workload) -> None:
    state = MagicMock()
    state.runs_controller = False
    state.peer_cluster.bootstrap_controller = "10.10.10.10:9097"
    manager = ControllerManager(state=state, workload=fake_workload)
    fake_workload.run_bin_command.return_value = METADATA_QUORUM_STUB["describe-replication"]

    state.unit_broker.broker_id = 100
    assert manager.broker_active()

    # broker with -1 lag
    state.unit_broker.broker_id = 101
    assert not manager.broker_active()

    # broker which does not exist
    state.unit_broker.broker_id = 102
    assert not manager.broker_active()


def test_add_controller(fake_workload) -> None:
    state = MagicMock()
    state.peer_cluster.bootstrap_controller = "10.10.10.10:9097"
    fake_workload.run_bin_command.return_value = "done"
    manager = ControllerManager(state=state, workload=fake_workload)

    manager.add_controller("10.10.10.10:9097")
    assert fake_workload.run_bin_command.call_args.kwargs["bin_keyword"] == "metadata-quorum"
    _args = " ".join(fake_workload.run_bin_command.call_args.kwargs["bin_args"])
    assert "add-controller" in _args
    assert f"--command-config {fake_workload.paths.conf_path}/kraft-client.properties" in _args
    assert "--bootstrap-controller 10.10.10.10:9097" in _args

    # DuplicateVoterException is fine
    fake_workload.run_bin_command = _raises_process_error(
        stderr=METADATA_QUORUM_STUB["duplicate-voter-exception"]
    )
    manager.add_controller("10.10.10.10:9097")

    fake_workload.run_bin_command = _raises_process_error(
        stderr="org.apache.kafka.common.errors.InvalidConfigurationException"
    )
    with pytest.raises(CalledProcessError):
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
    assert f"--command-config {fake_workload.paths.conf_path}/kraft-client.properties" in _args
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
