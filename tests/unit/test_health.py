#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from ops.testing import Harness

from charm import KafkaCharm
from literals import CHARM_KEY

logger = logging.getLogger(__name__)

CONFIG = str(yaml.safe_load(Path("./config.yaml").read_text()))
ACTIONS = str(yaml.safe_load(Path("./actions.yaml").read_text()))
METADATA = str(yaml.safe_load(Path("./metadata.yaml").read_text()))


@pytest.fixture
def harness():
    harness = Harness(KafkaCharm, meta=METADATA)
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
    example_log = "2023-03-29T16:57:48+01:00 charmed-kafka.daemon[1314231]: [2023-03-29 16:57:48,700] INFO [BrokerToControllerChannelManager broker=0 name=alterPartition]: Recorded new controller, from now on will use node marc-pc.localdomain:9092 (id: 0 rack: null) (kafka.server.BrokerToControllerRequestThread)"

    with patch("snap.snap.Snap.logs", return_value=example_log):
        assert harness.charm.health._service_pid == 1314231


def test_check_vm_swappiness(harness):
    with (
        patch("health.KafkaHealth._get_vm_swappiness", return_value=5),
        patch("health.KafkaHealth._check_file_descriptors", return_value=True),
        patch("health.KafkaHealth._check_memory_maps", return_value=True),
    ):
        assert not harness.charm.health._check_vm_swappiness()
        assert not harness.charm.health.machine_configured()


def test_get_partitions_size(harness):
    example_log_dirs = 'Querying brokers for log directories information\nReceived log directory information from brokers 0\n{"version":1,"brokers":[{"broker":0,"logDirs":[{"logDir":"/var/snap/charmed-kafka/common/var/lib/kafka/data/0","error":null,"partitions":[{"partition":"NEW-TOPIC-2-4","size":394,"offsetLag":0,"isFuture":false},{"partition":"NEW-TOPIC-2-3","size":394,"offsetLag":0,"isFuture":false},{"partition":"NEW-TOPIC-2-2","size":392,"offsetLag":0,"isFuture":false},{"partition":"NEW-TOPIC-2-1","size":392,"offsetLag":0,"isFuture":false},{"partition":"NEW-TOPIC-2-0","size":393,"offsetLag":0,"isFuture":false}]}]}]}\n'

    with patch("snap.KafkaSnap.run_bin_command", return_value=example_log_dirs):
        assert harness.charm.health._get_partitions_size() == (5, 393)


def test_check_file_descriptors_no_listeners(harness):
    with patch("snap.KafkaSnap.run_bin_command") as patched_run_bin:
        assert harness.charm.health._check_file_descriptors()
        assert patched_run_bin.call_count == 0


def test_machine_configured_fails_near_mmap_limit(harness):
    with (
        patch("health.KafkaHealth._check_memory_maps", return_value=False),
        patch("health.KafkaHealth._check_file_descriptors", return_value=True),
        patch("health.KafkaHealth._check_vm_swappiness", return_value=True),
    ):
        assert not harness.charm.health.machine_configured()


def test_machine_configured_fails_near_file_limit(harness):
    with (
        patch("health.KafkaHealth._check_memory_maps", return_value=True),
        patch("health.KafkaHealth._check_file_descriptors", return_value=False),
        patch("health.KafkaHealth._check_vm_swappiness", return_value=True),
    ):
        assert not harness.charm.health.machine_configured()


def test_machine_configured_succeeds(harness):
    with (
        patch("health.KafkaHealth._check_memory_maps", return_value=True),
        patch("health.KafkaHealth._check_file_descriptors", return_value=True),
        patch("health.KafkaHealth._check_vm_swappiness", return_value=True),
    ):
        assert harness.charm.health.machine_configured()
