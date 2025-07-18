#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import datetime
import inspect
import time
from unittest.mock import mock_open, patch

import pytest

from core.workload import WorkloadBase
from literals import SUBSTRATE
from workload import KafkaWorkload

if SUBSTRATE == "vm":
    from charms.operator_libs_linux.v2.snap import SnapError

pytestmark = [
    pytest.mark.broker,
    pytest.mark.skipif(SUBSTRATE == "k8s", reason="workload tests not needed for K8s"),
]


@pytest.fixture()
def fake_workload(tmp_path_factory, monkeypatch) -> WorkloadBase:
    monkeypatch.undo()
    workload = KafkaWorkload()
    workload.paths.conf_path = tmp_path_factory.mktemp("workload")
    return workload


@pytest.mark.skip
def test_modify_time_functionality(fake_workload: WorkloadBase):
    test_path = fake_workload.paths.server_properties
    start = time.time()

    with open(test_path, "w") as f:
        f.write("test\n")

    first_modified = fake_workload.modify_time(test_path)
    assert first_modified > start

    with open(test_path, "a") as f:
        f.write("append to test\n")
        f.flush()

    assert fake_workload.modify_time(test_path) > first_modified


def test_last_restart_parses_snap_changes_correctly(patched_exec, monkeypatch):
    monkeypatch.undo()
    patched_exec.return_value = inspect.cleandoc(
        """
    ID   Status  Spawn                 Ready                 Summary
    4    Done    2025-07-14T16:15:32Z  2025-07-14T16:18:34Z  Install "charmed-kafka" snap
    6    Done    2025-07-14T16:18:34Z  2025-07-14T16:18:34Z  Connect charmed-kafka:removable-media to snapd:removable-media
    7    Done    2025-07-14T16:18:34Z  2025-07-14T16:18:34Z  Hold general refreshes for "charmed-kafka"
    8    Done    2025-07-14T16:20:04Z  2025-07-14T16:20:04Z  Running service command
    9    Done    2025-07-14T16:24:06Z  2025-07-14T16:24:07Z  Running service command
    10   Done    2025-07-14T16:26:11Z  2025-07-14T16:26:12Z  Running service command
    """
    )

    assert (
        KafkaWorkload().last_restart
        == datetime.datetime(2025, 7, 14, 16, 26, 12, tzinfo=datetime.timezone.utc).timestamp()
    )


def test_run_bin_command_args(patched_exec):
    """Checks KAFKA_OPTS env-var and zk-tls flag present in all snap commands."""
    KafkaWorkload().run_bin_command(bin_keyword="configs", bin_args=["--list"], opts=["-Djava"])

    assert "charmed-kafka.configs" in patched_exec.call_args.args[0].split()
    assert "-Djava" == patched_exec.call_args.args[0].split()[0]
    assert "--list" == patched_exec.call_args.args[0].split()[-1]


def test_get_service_pid_raises(monkeypatch):
    """Checks get_service_pid raises if PID cannot be found."""
    monkeypatch.undo()
    with (
        patch(
            "builtins.open",
            new_callable=mock_open,
            read_data="0::/system.slice/snap.charmed-zookeeper.daemon.service",
        ),
        patch("subprocess.check_output", return_value="123"),
        pytest.raises(SnapError),
    ):
        KafkaWorkload().get_service_pid()


def test_get_service_pid_raises_no_pid(monkeypatch):
    """Checks get_service_pid raises if PID cannot be found."""
    monkeypatch.undo()
    with (
        patch("subprocess.check_output", return_value=""),
        pytest.raises(SnapError),
    ):
        KafkaWorkload().get_service_pid()
