#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest
import yaml
from ops.testing import Harness

from charm import KafkaCharm
from literals import CHARM_KEY, JVM_MEM_MAX_GB, JVM_MEM_MIN_GB, SUBSTRATE

logger = logging.getLogger(__name__)

CONFIG = str(yaml.safe_load(Path("./config.yaml").read_text()))
ACTIONS = str(yaml.safe_load(Path("./actions.yaml").read_text()))
METADATA = str(yaml.safe_load(Path("./metadata.yaml").read_text()))

pytestmark = pytest.mark.skipif(SUBSTRATE == "k8s", reason="health checks not used on K8s")


@pytest.fixture
def harness():
    harness = Harness(KafkaCharm, meta=METADATA, actions=ACTIONS, config=CONFIG)
    harness.add_relation("restart", CHARM_KEY)
    harness._update_config(
        {
            "log_retention_ms": "-1",
            "compression_type": "producer",
        }
    )
    harness.begin()
    storage_metadata = getattr(harness.charm, "meta").storages["data"]
    min_storages = storage_metadata.multiple_range[0] if storage_metadata.multiple_range else 0
    with harness.hooks_disabled():
        harness.add_storage(storage_name="data", count=min_storages, attach=True)

    return harness


def test_service_pid(harness):
    with (
        patch(
            "builtins.open",
            new_callable=mock_open,
            read_data="0::/system.slice/snap.charmed-kafka.daemon.service",
        ),
        patch("subprocess.check_output", return_value="1314231"),
    ):
        assert harness.charm.health._service_pid == 1314231


def test_check_vm_swappiness(harness):
    with (
        patch("health.KafkaHealth._get_vm_swappiness", return_value=5),
        patch("health.KafkaHealth._check_file_descriptors", return_value=True),
        patch("health.KafkaHealth._check_memory_maps", return_value=True),
        patch("health.KafkaHealth._check_total_memory", return_value=True),
    ):
        assert not harness.charm.health._check_vm_swappiness()
        assert not harness.charm.health.machine_configured()


@pytest.mark.parametrize("total_mem_kb", [5741156, 65741156])
@pytest.mark.parametrize(
    "profile,limit", [("testing", JVM_MEM_MIN_GB), ("production", JVM_MEM_MAX_GB)]
)
def test_check_total_memory_testing_profile(harness, total_mem_kb, profile, limit):
    harness._update_config({"profile": profile})

    with patch("workload.KafkaWorkload.read", return_value=[f"MemTotal:      {total_mem_kb} kB"]):
        if total_mem_kb / 1000000 <= limit:
            assert not harness.charm.health._check_total_memory()
        else:
            assert harness.charm.health._check_total_memory()


def test_get_partitions_size(harness):
    example_log_dirs = 'Querying brokers for log directories information\nReceived log directory information from brokers 0\n{"version":1,"brokers":[{"broker":0,"logDirs":[{"logDir":"/var/snap/charmed-kafka/common/var/lib/kafka/data/0","error":null,"partitions":[{"partition":"NEW-TOPIC-2-4","size":394,"offsetLag":0,"isFuture":false},{"partition":"NEW-TOPIC-2-3","size":394,"offsetLag":0,"isFuture":false},{"partition":"NEW-TOPIC-2-2","size":392,"offsetLag":0,"isFuture":false},{"partition":"NEW-TOPIC-2-1","size":392,"offsetLag":0,"isFuture":false},{"partition":"NEW-TOPIC-2-0","size":393,"offsetLag":0,"isFuture":false}]}]}]}\n'

    with patch("workload.KafkaWorkload.run_bin_command", return_value=example_log_dirs):
        assert harness.charm.health._get_partitions_size() == (5, 393)


def test_check_file_descriptors_no_listeners(harness):
    with patch("workload.KafkaWorkload.run_bin_command") as patched_run_bin:
        assert harness.charm.health._check_file_descriptors()
        assert patched_run_bin.call_count == 0


@pytest.mark.parametrize("mmap", [True, False])
@pytest.mark.parametrize("fd", [True, False])
@pytest.mark.parametrize("swap", [True, False])
@pytest.mark.parametrize("mem", [True, False])
def test_machine_configured_succeeds_and_fails(harness, mmap, fd, swap, mem):
    with (
        patch("health.KafkaHealth._check_memory_maps", return_value=mmap),
        patch("health.KafkaHealth._check_file_descriptors", return_value=fd),
        patch("health.KafkaHealth._check_vm_swappiness", return_value=swap),
        patch("health.KafkaHealth._check_total_memory", return_value=mem),
    ):
        if all([mmap, fd, swap, mem]):
            assert harness.charm.health.machine_configured()
        else:
            assert not harness.charm.health.machine_configured()
