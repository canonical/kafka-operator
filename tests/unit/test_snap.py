#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import subprocess
import pytest
from unittest.mock import patch

from charms.kafka.v0.kafka_snap import KafkaSnap


def test_run_bin_command_raises():
    with pytest.raises(subprocess.CalledProcessError):
        KafkaSnap.run_bin_command("stuff", ["to"], ["fail"])

def test_run_bin_command_args():
    with patch("subprocess.check_output") as patched:
        KafkaSnap.run_bin_command("configs", ["--list"], ["-Djava"])
    
    assert ('KAFKA_OPTS=-Djava kafka.configs --list',) in list(patched.call_args)
