#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
from pathlib import Path
from typing import cast
from unittest.mock import mock_open, patch

import pytest
import yaml
from scenario import Container, Context, State

from charm import KafkaCharm
from literals import (
    CONTAINER,
    JVM_MEM_MAX_GB,
    JVM_MEM_MIN_GB,
    SUBSTRATE,
)

pytestmark = [
    pytest.mark.broker,
    pytest.mark.skipif(SUBSTRATE == "k8s", reason="health checks not used on K8s"),
]


logger = logging.getLogger(__name__)


CONFIG = yaml.safe_load(Path("./config.yaml").read_text())
ACTIONS = yaml.safe_load(Path("./actions.yaml").read_text())
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())


@pytest.fixture()
def charm_configuration():
    """Enable direct mutation on configuration dict."""
    return json.loads(json.dumps(CONFIG))


@pytest.fixture()
def base_state():
    if SUBSTRATE == "k8s":
        state = State(leader=True, containers=[Container(name=CONTAINER, can_connect=True)])

    else:
        state = State(leader=True)

    return state


@pytest.fixture()
def ctx() -> Context:
    ctx = Context(KafkaCharm, meta=METADATA, config=CONFIG, actions=ACTIONS, unit_id=0)
    return ctx


def test_service_pid(ctx: Context, base_state: State) -> None:
    # Given
    state_in = base_state

    # When
    with (
        patch(
            "builtins.open",
            new_callable=mock_open,
            read_data="0::/system.slice/snap.charmed-kafka.daemon.service",
        ),
        patch("subprocess.check_output", return_value="1314231"),
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)

        # Then
        assert charm.broker.health._service_pid == 1314231


def test_check_vm_swappiness(ctx: Context, base_state: State) -> None:
    # Given
    state_in = base_state

    # When
    with (
        patch("health.KafkaHealth._get_vm_swappiness", return_value=5),
        patch("health.KafkaHealth._check_file_descriptors", return_value=True),
        patch("health.KafkaHealth._check_memory_maps", return_value=True),
        patch("health.KafkaHealth._check_total_memory", return_value=True),
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)

        # Then
        assert not charm.broker.health._check_vm_swappiness()
        assert not charm.broker.health.machine_configured()


@pytest.mark.parametrize("total_mem_kb", [5741156, 65741156])
@pytest.mark.parametrize(
    "profile,limit", [("testing", JVM_MEM_MIN_GB), ("production", JVM_MEM_MAX_GB)]
)
def test_check_total_memory_testing_profile(
    charm_configuration: dict, base_state: State, total_mem_kb: int, profile: str, limit: int
) -> None:
    # Given
    charm_configuration["options"]["profile"]["default"] = profile
    state_in = base_state
    ctx = Context(
        KafkaCharm, meta=METADATA, config=charm_configuration, actions=ACTIONS, unit_id=0
    )

    # When
    with (
        patch("workload.KafkaWorkload.read", return_value=[f"MemTotal:      {total_mem_kb} kB"]),
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)

        # Then
        if total_mem_kb / 1000000 <= limit:
            assert not charm.broker.health._check_total_memory()
        else:
            assert charm.broker.health._check_total_memory()


def test_get_partitions_size(ctx: Context, base_state: State) -> None:
    # Given
    example_log_dirs = 'Querying brokers for log directories information\nReceived log directory information from brokers 0\n{"version":1,"brokers":[{"broker":0,"logDirs":[{"logDir":"/var/snap/charmed-kafka/common/var/lib/kafka/data/0","error":null,"partitions":[{"partition":"NEW-TOPIC-2-4","size":394,"offsetLag":0,"isFuture":false},{"partition":"NEW-TOPIC-2-3","size":394,"offsetLag":0,"isFuture":false},{"partition":"NEW-TOPIC-2-2","size":392,"offsetLag":0,"isFuture":false},{"partition":"NEW-TOPIC-2-1","size":392,"offsetLag":0,"isFuture":false},{"partition":"NEW-TOPIC-2-0","size":393,"offsetLag":0,"isFuture":false}]}]}]}\n'
    state_in = base_state

    # When
    with (
        patch("workload.KafkaWorkload.run_bin_command", return_value=example_log_dirs),
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)

        # Then
        assert charm.broker.health._get_partitions_size() == (5, 393)


def test_check_file_descriptors_no_listeners(ctx: Context, base_state: State) -> None:
    # Given
    state_in = base_state

    # When
    with (
        patch("workload.KafkaWorkload.run_bin_command") as patched_run_bin,
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)

        # Then
        assert charm.broker.health._check_file_descriptors()
        assert patched_run_bin.call_count == 0


@pytest.mark.parametrize("mmap", [True, False])
@pytest.mark.parametrize("fd", [True, False])
@pytest.mark.parametrize("swap", [True, False])
@pytest.mark.parametrize("mem", [True, False])
def test_machine_configured_succeeds_and_fails(
    ctx: Context, base_state: State, mmap: bool, fd: bool, swap: bool, mem: bool
) -> None:
    # Given
    state_in = base_state

    # When
    with (
        patch("health.KafkaHealth._check_memory_maps", return_value=mmap),
        patch("health.KafkaHealth._check_file_descriptors", return_value=fd),
        patch("health.KafkaHealth._check_vm_swappiness", return_value=swap),
        patch("health.KafkaHealth._check_total_memory", return_value=mem),
        ctx(ctx.on.config_changed(), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)

        # Then
        if all([mmap, fd, swap, mem]):
            assert charm.broker.health.machine_configured()
        else:
            assert not charm.broker.health.machine_configured()
