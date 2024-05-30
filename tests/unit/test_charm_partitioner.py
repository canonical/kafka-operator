#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from charms.operator_libs_linux.v0.sysctl import ApplyError
from ops.testing import Harness
from src.literals import OS_REQUIREMENTS, Role, Status

from charm import KafkaCharm
from literals import (
    CONTAINER,
    SUBSTRATE,
)

pytestmark = pytest.mark.partitioner

logger = logging.getLogger(__name__)


CONFIG = str(yaml.safe_load(Path("./config.yaml").read_text()))
ACTIONS = str(yaml.safe_load(Path("./actions.yaml").read_text()))
METADATA = str(yaml.safe_load(Path("./metadata.yaml").read_text()))


@pytest.fixture
def harness() -> Harness:
    harness = Harness(KafkaCharm, meta=METADATA, actions=ACTIONS, config=CONFIG)

    if SUBSTRATE == "k8s":
        harness.set_can_connect(CONTAINER, True)

    harness._update_config({"role": "partitioner"})
    harness.begin()
    return harness


def test_start_with_correct_role(harness: Harness):
    assert harness.charm.config["role"] == Role.PARTITIONER


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="sysctl config not used on K8s")
def test_install_blocks_snap_install_failure(harness: Harness):
    """Checks unit goes to BlockedStatus after snap failure on install hook."""
    with patch("workload.KafkaWorkload.install", return_value=False):
        harness.charm.on.install.emit()
        assert harness.charm.unit.status == Status.SNAP_NOT_INSTALLED.value.status


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="sysctl config not used on K8s")
def test_install_configures_os(harness: Harness, patched_sysctl_config):
    with patch("workload.KafkaWorkload.install"):
        harness.charm.on.install.emit()
        patched_sysctl_config.assert_called_once_with(OS_REQUIREMENTS)


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="sysctl config not used on K8s")
def test_install_sets_status_if_os_config_fails(harness: Harness, patched_sysctl_config):
    with patch("workload.KafkaWorkload.install"):
        patched_sysctl_config.side_effect = ApplyError("Error setting values")
        harness.charm.on.install.emit()

        assert harness.charm.unit.status == Status.SYSCONF_NOT_POSSIBLE.value.status
