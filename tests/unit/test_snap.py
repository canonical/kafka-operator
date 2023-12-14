#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import subprocess
from unittest.mock import patch, mock_open

import pytest
from charms.operator_libs_linux.v1.snap import SnapError

from snap import KafkaSnap


def test_run_bin_command_raises():
    """Checks failed snap command raises CalledProcessError."""
    with pytest.raises(subprocess.CalledProcessError):
        KafkaSnap.run_bin_command("stuff", ["to"], ["fail"])


def test_run_bin_command_args():
    """Checks KAFKA_OPTS env-var and zk-tls flag present in all snap commands."""
    with patch("subprocess.check_output") as patched:
        KafkaSnap.run_bin_command(bin_keyword="configs", bin_args=["--list"], opts=["-Djava"])

        assert "charmed-kafka.configs" in patched.call_args.args[0].split()
        assert "-Djava" == patched.call_args.args[0].split()[0]
        assert "--list" == patched.call_args.args[0].split()[-1]


def test_get_service_pid_raises():
    """Checks get_service_pid raises if PID cannot be found."""
    with (
            patch(
                "builtins.open",
                new_callable=mock_open,
                read_data="0::/system.slice/snap.charmed-zookeeper.daemon.service"
        ) as mock_file,
        patch("subprocess.check_output", return_value="123"),
        pytest.raises(SnapError),
    ):
        KafkaSnap().get_service_pid()


def test_get_service_pid_raises():
    """Checks get_service_pid raises if PID cannot be found."""
    with (
        patch("subprocess.check_output", return_value=""),
        pytest.raises(SnapError),
    ):
        KafkaSnap().get_service_pid()
