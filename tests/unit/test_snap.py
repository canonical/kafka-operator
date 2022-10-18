#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import subprocess
from unittest.mock import patch

import pytest

from snap import KafkaSnap


def test_run_bin_command_raises():
    with pytest.raises(subprocess.CalledProcessError):
        KafkaSnap.run_bin_command("stuff", ["to"], ["fail"])


def test_run_bin_command_args():
    with patch("subprocess.check_output") as patched:
        KafkaSnap.run_bin_command("configs", ["--list"], ["-Djava"])

        found_tls = False
        found_opts = False
        for arg in patched.call_args.args:
            if "--zk-tls-config-file" in arg:
                found_tls = True
            if "KAFKA_OPTS=" in arg:
                found_opts = True

        assert found_tls, "--zk-tls-config-file flag not found"
        assert found_opts, "KAFKA_OPTS not found"
