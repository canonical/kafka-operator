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
def patched_etc_environment():
    with patch("managers.config.KafkaConfigManager.set_environment") as etc_env:
        yield etc_env


@pytest.fixture(autouse=True)
def patched_workload_write():
    with patch("workload.KafkaWorkload.write") as workload_write:
        yield workload_write


@pytest.fixture(autouse=True)
def patched_sysctl_config():
    if SUBSTRATE == "vm":
        with patch("charm.sysctl.Config.configure") as sysctl_config:
            yield sysctl_config
    else:
        yield


@pytest.fixture(autouse=True)
def patched_exec():
    with patch("workload.KafkaWorkload.exec") as patched_exec:
        yield patched_exec


@pytest.fixture()
def patched_health_machine_configured():
    if SUBSTRATE == "vm":
        with patch(
            "health.KafkaHealth.machine_configured", return_value=True
        ) as machine_configured:
            yield machine_configured
    else:
        yield
