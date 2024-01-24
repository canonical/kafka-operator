#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
from unittest.mock import patch

import pytest
from src.literals import INTERNAL_USERS, SUBSTRATE


@pytest.fixture(scope="module")
def zk_data() -> dict[str, str]:
    return {
        "username": "glorfindel",
        "password": "mellon",
        "endpoints": "10.10.10.10",
        "chroot": "/kafka",
        "uris": "10.10.10.10:2181",
        "tls": "disabled",
    }


@pytest.fixture(scope="module")
def passwords_data() -> dict[str, str]:
    return {f"{user}-password": "mellon" for user in INTERNAL_USERS}


@pytest.fixture(autouse=True)
def patched_pebble_restart(mocker):
    mocker.patch("ops.model.Container.restart")


@pytest.fixture(autouse=True)
def patched_sysctl_config():
    with patch("charm.sysctl.Config.configure") as sysctl_config:
        yield sysctl_config


@pytest.fixture(autouse=True)
def patched_etc_environment():
    with patch("managers.config.KafkaConfigManager.set_environment") as etc_env:
        yield etc_env


@pytest.fixture(autouse=True)
def patched_workload_write():
    with patch("vm_workload.KafkaWorkload.write") as workload_write:
        yield workload_write


@pytest.fixture()
def patched_ownership_and_mode():
    if SUBSTRATE == "vm":
        with (
            patch("vm_workload.KafkaWorkload.set_snap_ownership"),
            patch("vm_workload.KafkaWorkload.set_snap_mode_bits"),
        ):
            yield
    else:
        yield
