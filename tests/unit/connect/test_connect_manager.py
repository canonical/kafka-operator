#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import random
import re
import subprocess
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from common.single_kernel_kafka.core.connect_models import ConnectContext as Context
from common.single_kernel_kafka.core.literals import ConnectLiterals
from common.single_kernel_kafka.core.workload import ConnectPaths, WorkloadBase
from common.single_kernel_kafka.managers.connect import ConnectManager, PluginDownloadFailedError

from ..helpers import SUBSTRATE, SUBSTRATE_CLS

logger = logging.getLogger(__name__)


STATUS_RESPONSE = json.load(open("./tests/unit/connect/data/status_response.json", "r"))


class FakeDir:
    """Fake directory object, usable as return value for `os.scandir`."""

    def __init__(self, name):
        self.name = name

    @property
    def is_dir(self) -> bool:
        return True


@pytest.fixture()
def connect_manager():
    """A ConnectManager instance with mock `Workload` and `Context`."""
    mock_workload = MagicMock(spec=WorkloadBase)
    mock_workload.connect_paths = ConnectPaths(substrate=SUBSTRATE)
    mock_context = MagicMock(spec=Context)

    hash1 = f"{random.getrandbits(256):032x}"
    hash2 = f"{random.getrandbits(256):032x}"

    mock_workload.ls = lambda _: [
        FakeDir("plugin-a"),
        FakeDir(f"relation-1-{hash1}"),
        FakeDir("plugin-b"),
        FakeDir(f"relation-7-{hash2}"),
    ]
    mock_workload.dir_exists = lambda: True

    mgr = ConnectManager(context=mock_context, workload=mock_workload)
    yield mgr


def test_loaded_client_plugins(connect_manager: ConnectManager) -> None:
    """Checks ConnectManager appropriately distinguishes client plugins from user provided plugins."""
    assert connect_manager.loaded_client_plugins == {"relation-1", "relation-7"}


@pytest.mark.parametrize(
    "test_data",
    [
        ("connector", False),
        ("my-app", False),
        (f"long-connector-name-r11_{uuid.uuid4().hex}", True),
        (f"app-r11_{uuid.uuid4().hex}", True),
        (uuid.uuid4().hex, False),
    ],
)
def test_managed_connector_regexes(
    connect_manager: ConnectManager, test_data: tuple[str, bool]
) -> None:
    """Checks ConnectManager appropriately distinguishes integrator-managed connectors from the custom, user-defined ones."""
    assert (
        bool(re.match(connect_manager._managed_connector_regex(11), test_data[0])) == test_data[1]
    )
    # check we don't mix up `r11_uuid` with `r1_uuid`
    assert not bool(re.match(connect_manager._managed_connector_regex(1), test_data[0]))


def test_connect_manager_request(connect_manager: ConnectManager) -> None:
    """Tests ConnectManager._request basic functionality."""
    with patch("requests.request", return_value=MagicMock()) as fake_request:
        connect_manager.context.rest_uri = "http://some-url:8083"
        connect_manager._request("GET", "/")

    assert fake_request.call_args[0][0] == "GET"
    assert str(fake_request.call_args[0][1]).startswith("http://some-url:8083")
    assert fake_request.call_args[1].get("timeout") == connect_manager.REQUEST_TIMEOUT


def test_untar_plugin(connect_manager: ConnectManager) -> None:
    """Tests ConnectManager._untar_plugin functionality."""
    connect_manager._untar_plugin(Path("/path/to/plugin.tar.gz"), Path("/path/to/var/plugins/"))
    assert " ".join(connect_manager.workload.exec.call_args[0][0]).startswith("tar -xvzf")

    connect_manager._untar_plugin(Path("/path/to/plugin.tar"), Path("/path/to/var/plugins/"))
    assert " ".join(connect_manager.workload.exec.call_args[0][0]).startswith("tar -xvf")

    connect_manager._untar_plugin(Path("/path/to/plugin"), Path("/path/to/var/plugins/"))
    assert " ".join(connect_manager.workload.exec.call_args[0][0]).startswith("tar -xvf")


def test_attach_empty_plugin(
    connect_manager: ConnectManager, caplog: pytest.LogCaptureFixture
) -> None:
    """Tests attaching an empty TAR file leads to no-op, followed by a log message by ConnectManager."""
    caplog.set_level(logging.DEBUG)
    connect_manager._plugin_checksum = (
        lambda _: subprocess.check_output(  # pyright: ignore[reportAttributeAccessIssue]
            f"sha256sum ./connect_{SUBSTRATE_CLS.lower()}/empty.tar",
            shell=True,
            universal_newlines=True,
        )
        .strip()
        .split()[0]
    )
    assert (
        connect_manager._plugin_checksum(Path("emptyfile"))
        == ConnectLiterals.EMPTY_PLUGIN_CHECKSUM
    )
    connect_manager.load_plugin(Path(f"./connect_{SUBSTRATE_CLS.lower()}/empty.tar"))
    assert "Plugin is empty, skipping..." in caplog.messages


@pytest.mark.parametrize("with_connection_error", [True, False])
@pytest.mark.parametrize("directory_exists", [True, False])
def test_load_plugin_from_url(
    connect_manager: ConnectManager,
    with_connection_error: bool,
    directory_exists: bool,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Checks `load_plugin_from_url` method functionality under different conditions."""

    def _mock_get(*args, **kwargs):
        if with_connection_error:
            raise ConnectionError("Connection Error")

        fake_response = MagicMock()
        fake_response.iter_content.return_value = [b"chunk1", b"chunk2", b"chunk3"]
        return fake_response

    def _mock_mkdir(*args, **kwargs):
        # This is to simulate file exists exception.
        subprocess.check_output(
            "mkdir ./tests", shell=True, stderr=subprocess.PIPE, universal_newlines=True
        )

    # we need to undo monkeypatch here since `tempfile` needs `os.scandir`.
    monkeypatch.undo()
    # instead, we'll patch the `reload_plugins` method for this particular test.
    connect_manager.reload_plugins = lambda: None

    fake_url = "http://some-plugin-url"
    with monkeypatch.context() as m:
        m.setattr("requests.get", _mock_get)
        caplog.set_level(logging.DEBUG)

        if not any([with_connection_error, directory_exists]):
            connect_manager.load_plugin_from_url(fake_url)
            assert f"Plugin {fake_url} loaded successfully." in caplog.messages
            return

        if with_connection_error:
            with pytest.raises(PluginDownloadFailedError):
                connect_manager.load_plugin_from_url(fake_url)
            return

        # plugin exists!
        connect_manager.workload.mkdir = _mock_mkdir
        connect_manager.load_plugin_from_url(fake_url)
        assert "Plugin already exists." in caplog.messages


def test_connector_lifecycle_management(
    connect_manager: ConnectManager, caplog: pytest.LogCaptureFixture
) -> None:
    """Tests `connector_status` and `stop_connector` methods used for connector lifecycle management."""
    with (patch("requests.request") as _fake_request,):
        response = MagicMock()
        response.json.return_value = STATUS_RESPONSE
        _fake_request.return_value = response

        health_response = MagicMock()
        health_response.status_code = 200
        connect_manager._get_health = lambda: health_response

        assert len(connect_manager.connectors) == 3

        expected_status = {1: "UNKNOWN", 11: "STOPPED", 12: "RUNNING"}

        response.status_code = 204
        for rel_id in (1, 11):
            assert connect_manager.connector_status(rel_id).value == expected_status[rel_id]
            connect_manager.delete_connector(rel_id)

        assert connect_manager.connector_status(12).value == expected_status[12]

        connect_manager.delete_connector(12)
        assert caplog.messages[-1] == "Successfully deleted connector for relation ID=12."

        response.status_code = 500
        connect_manager.delete_connector(12)
        assert caplog.messages[-1].startswith("Unable to delete connector, details:")


@pytest.mark.parametrize("status_code,correct_response", [(200, True), (500, False), (404, False)])
def test_health_check(
    connect_manager: ConnectManager, status_code: int, correct_response: bool
) -> None:
    """Tests ConnectManager health checking functionality."""
    with patch("requests.request") as _fake_request:
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = {}
        _fake_request.return_value = response

        assert bool(connect_manager.healthy) is correct_response
