#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import subprocess
from unittest.mock import patch

import pytest

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
