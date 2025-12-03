#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import contextlib
import http.server
import json
import logging
import os
import ssl
import subprocess
from multiprocessing import Process
from typing import Any, Mapping
from unittest.mock import MagicMock

import pytest
import yaml
from charmlibs import pathops
from src.core.cluster import KafkaBroker
from src.core.structured_config import CharmConfig
from src.core.workload import CharmedKafkaPaths, WorkloadBase
from src.literals import BROKER, SUBSTRATE, TLSScope
from src.managers.tls import TLSManager
from tests.unit.helpers import TLSArtifacts, generate_tls_artifacts

logger = logging.getLogger(__name__)

UNIT_NAME = "kafka/0"
INTERNAL_ADDRESS = "10.10.10.10"
BIND_ADDRESS = "10.20.20.20"
KEYTOOL = "keytool"
JKS_UNIT_TEST_FILE = "tests/unit/TestJKS.java"


def _exec(
    command: list[str] | str,
    env: Mapping[str, str] | None = None,
    working_dir: str | None = None,
    **kwargs: Any,
) -> str:
    _command = " ".join(command) if isinstance(command, list) else command

    for bin in ("chown", "chmod"):
        if _command.startswith(bin):
            return "ok"

    try:
        output = subprocess.check_output(
            command,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            shell=isinstance(command, str),
            env=env,
            cwd=working_dir,
        )
        return output
    except subprocess.CalledProcessError as e:
        if kwargs["log_on_error"]:
            logger.error(f"{e.stdout}, {e.stderr}")
        raise e


try:
    _exec(KEYTOOL)
    _exec("java -version")
    JAVA_TESTS_DISABLED = False
except subprocess.CalledProcessError:
    JAVA_TESTS_DISABLED = True


@contextlib.contextmanager
def simple_ssl_server(certfile: str, keyfile: str, port: int = 10443):
    httpd = http.server.HTTPServer(("127.0.0.1", port), http.server.SimpleHTTPRequestHandler)
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(certfile=certfile, keyfile=keyfile)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)

    process = Process(target=httpd.serve_forever)
    process.start()
    yield

    process.kill()


class JKSError(Exception):
    """Error raised when JKS unit test fails."""


def java_jks_test(truststore_path: str, truststore_password: str, ssl_server_port: int = 10443):
    cmd = [
        "java",
        "-Djavax.net.debug=ssl:handshake",
        f"-Djavax.net.ssl.trustStore={truststore_path}",
        f'-Djavax.net.ssl.trustStorePassword="{truststore_password}"',
        JKS_UNIT_TEST_FILE,
        f"https://localhost:{ssl_server_port}",
    ]

    if os.system(f"{' '.join(cmd)} >/dev/null 2>&1"):
        raise JKSError("JKS unit test failed, Check logs for details.")


@pytest.fixture()
def tls_manager(tmp_path_factory, monkeypatch):
    """A TLSManager instance with minimal functioning mock `Workload` and `State`."""
    monkeypatch.undo()
    mock_workload = MagicMock(spec=WorkloadBase)
    mock_workload.write = lambda content, path: open(path, "w").write(content)
    mock_workload.exec = _exec
    mock_workload.root = pathops.LocalPath("/")
    mock_workload.paths = CharmedKafkaPaths(BROKER)
    mock_workload.paths.conf_path = tmp_path_factory.mktemp("workload")

    # Mock State
    mock_state = MagicMock()
    mock_broker_state = KafkaBroker(None, MagicMock(), MagicMock(), SUBSTRATE)
    mock_broker_state.relation_data = {}
    mock_state.unit_broker = mock_broker_state

    raw_config = {
        k.replace("-", "_"): v.get("default", "")
        for k, v in yaml.safe_load(open("config.yaml")).get("options", {}).items()
    }
    mgr = TLSManager(
        state=mock_state,
        workload=mock_workload,
        substrate=SUBSTRATE,
        config=CharmConfig(**raw_config),
    )
    mgr.keytool = KEYTOOL

    yield mgr


def _set_manager_state(
    mgr: TLSManager, tls_artifacts: TLSArtifacts | None = None, scope: TLSScope = TLSScope.CLIENT
) -> None:
    data = {
        f"{scope.value}-ca-cert": "ca",
        f"{scope.value}-chain": json.dumps(["certificate", "ca"]),
        f"{scope.value}-certificate": "certificate",
        f"{scope.value}-private-key": "private-key",
        "keystore-password": "keystore-password",
        "truststore-password": "truststore-password",
    }

    if tls_artifacts:
        data.update(
            {
                f"{scope.value}-ca-cert": tls_artifacts.ca,
                f"{scope.value}-chain": json.dumps(tls_artifacts.chain),
                f"{scope.value}-certificate": tls_artifacts.certificate,
                f"{scope.value}-private-key": tls_artifacts.private_key,
            }
        )

    mgr.state.unit_broker.relation_data = data


def _tls_manager_set_everything(mgr: TLSManager) -> None:
    mgr.set_ca()
    mgr.set_chain()
    mgr.set_server_key()
    mgr.set_certificate()
    mgr.set_bundle()
    mgr.set_keystore()
    mgr.set_truststore()


@pytest.mark.parametrize("tls_artifacts", [False, True], indirect=True)
def test_leaf_cert_validity_checker(tls_manager: TLSManager, tls_artifacts: TLSArtifacts) -> None:
    """Tests `TlSManager.is_valid_leaf_certificate()` method functionality."""
    assert tls_manager.is_valid_leaf_certificate(tls_artifacts.certificate)
    for cert in tls_artifacts.chain[1:]:
        assert not tls_manager.is_valid_leaf_certificate(cert)


@pytest.mark.skipif(
    JAVA_TESTS_DISABLED, reason=f"Can't locate {KEYTOOL} and/or java in the test environment."
)
@pytest.mark.parametrize(
    "tls_initialized", [False, True], ids=["TLS NOT initialized", "TLS initialized"]
)
@pytest.mark.parametrize(
    "tls_artifacts",
    [False, True],
    ids=["NO intermediate CA", "ONE intermediate CA"],
    indirect=True,
)
def test_tls_manager_set_methods(
    tls_manager: TLSManager,
    caplog: pytest.LogCaptureFixture,
    tls_initialized: bool,
    tls_artifacts: TLSArtifacts,
) -> None:
    """Tests the lifecycle of adding/removing certs from Java and TLSManager points of view."""
    _set_manager_state(tls_manager, tls_artifacts=tls_artifacts)

    if not tls_initialized:
        tls_manager.state.unit_broker.relation_data = {}
        tls_manager.state.peer_cluster.relation_data = {"tls": ""}

    caplog.set_level(logging.DEBUG)
    _tls_manager_set_everything(tls_manager)

    if not tls_initialized:
        assert not os.listdir(tls_manager.workload.paths.conf_path)
        return

    assert (
        tls_manager.workload.root / tls_manager.workload.paths.conf_path / "client-server.pem"
    ).read_text() == tls_artifacts.certificate
    assert (
        tls_manager.workload.root / tls_manager.workload.paths.conf_path / "client-server.key"
    ).read_text() == tls_artifacts.private_key
    assert (
        tls_manager.workload.root / tls_manager.workload.paths.conf_path / "client-bundle1.pem"
    ).read_text() == tls_artifacts.ca


@pytest.mark.skipif(
    JAVA_TESTS_DISABLED, reason=f"Can't locate {KEYTOOL} and/or java in the test environment."
)
@pytest.mark.parametrize(
    "with_intermediate", [False, True], ids=["NO intermediate CA", "ONE intermediate CA"]
)
def test_tls_manager_truststore_functionality(
    tls_manager: TLSManager,
    caplog: pytest.LogCaptureFixture,
    with_intermediate: bool,
    tmp_path_factory,
) -> None:
    tls_artifacts = generate_tls_artifacts(
        subject=UNIT_NAME,
        sans_ip=[INTERNAL_ADDRESS],
        sans_dns=[UNIT_NAME],
        with_intermediate=with_intermediate,
    )
    caplog.set_level(logging.DEBUG)
    _set_manager_state(tls_manager, tls_artifacts=tls_artifacts)
    _tls_manager_set_everything(tls_manager)

    # build another cert
    other_tls = generate_tls_artifacts(subject="some-app/0")

    tmp_dir = tmp_path_factory.mktemp("someapp")
    app_certfile = f"{tmp_dir}/app.pem"
    app_keyfile = f"{tmp_dir}/app.key"

    open(app_certfile, "w").write(other_tls.certificate)
    open(app_keyfile, "w").write(other_tls.private_key)

    truststore_path = f"{tls_manager.workload.paths.conf_path}/client-truststore.jks"

    for i in range(2 + int(with_intermediate)):
        assert f"bundle{i}" in tls_manager.trusted_certificates

    # haven't initialized peer tls yet.
    assert not tls_manager.peer_trusted_certificates

    with simple_ssl_server(certfile=app_certfile, keyfile=app_keyfile):
        # since we don't have the app cert/ca in our truststore, JKS test should fail.
        with pytest.raises(JKSError):
            java_jks_test(truststore_path, tls_manager.state.unit_broker.truststore_password)

        # Add the app cert
        filename = f"{tls_manager.workload.paths.conf_path}/some-app.pem"
        open(filename, "w").write(other_tls.certificate)
        tls_manager.import_cert(alias="some-app", filename="some-app.pem")

        # now the test should pass
        java_jks_test(truststore_path, tls_manager.state.unit_broker.truststore_password)

        # import again with the same alias
        filename = f"{tls_manager.workload.paths.conf_path}/other-file.pem"
        open(filename, "w").write(other_tls.certificate)
        tls_manager.import_cert(alias="some-app", filename="other-file.pem")
        assert "some-app" in tls_manager.trusted_certificates

        # check remove cert functionality
        tls_manager.remove_cert("some-app")
        assert "some-app" not in tls_manager.trusted_certificates

        # We don't have the cert anymore, so the JKS test should fail again.
        with pytest.raises(JKSError):
            java_jks_test(truststore_path, tls_manager.state.unit_broker.truststore_password)

        # Now add the app's CA cert instead of its own cert
        filename = f"{tls_manager.workload.paths.conf_path}/some-app-ca.pem"
        open(filename, "w").write(other_tls.ca)
        tls_manager.import_cert(alias="some-app-ca", filename="some-app-ca.pem")

        # the test should pass again
        java_jks_test(truststore_path, tls_manager.state.unit_broker.truststore_password)

    # remove some non-existing alias.
    tls_manager.remove_cert("other-app")
    log_record = caplog.records[-1]
    assert "alias <other-app> does not exist" in log_record.msg.lower()
    assert log_record.levelname == "DEBUG"


@pytest.mark.skipif(
    JAVA_TESTS_DISABLED, reason=f"Can't locate {KEYTOOL} and/or java in the test environment."
)
@pytest.mark.parametrize(
    "with_intermediate", [False, True], ids=["NO intermediate CA", "ONE intermediate CA"]
)
def test_tls_manager_sans(
    tls_manager: TLSManager,
    with_intermediate: bool,
) -> None:
    """Tests the lifecycle of adding/removing certs from Java and TLSManager points of view."""
    tls_artifacts = generate_tls_artifacts(
        subject=UNIT_NAME,
        sans_ip=[INTERNAL_ADDRESS],
        sans_dns=[UNIT_NAME],
        with_intermediate=with_intermediate,
    )
    # patch node_ip
    tls_manager.state.unit_broker.node_ip = "10.5.5.10"
    _set_manager_state(tls_manager, tls_artifacts=tls_artifacts)
    _tls_manager_set_everything(tls_manager)
    # check SANs
    current_sans = tls_manager.get_current_sans()
    assert current_sans and current_sans == {
        "sans_ip": [INTERNAL_ADDRESS],
        "sans_dns": [UNIT_NAME],
    }
    expected_sans = tls_manager.build_sans()
    # Because of the internal address mismatch:
    assert expected_sans != current_sans


def test_simulate_os_errors(tls_manager: TLSManager):
    """Checks TLSManager functionality when random OS Errors happen."""
    _set_manager_state(tls_manager)

    def _erroneous_hook(*args, **kwargs):
        raise subprocess.CalledProcessError(
            returncode=1, cmd="command", stderr="Some error occurred"
        )

    tls_manager.workload.exec = _erroneous_hook
    tls_manager.workload.write = _erroneous_hook

    for method in dir(TLSManager):
        if not method.startswith("set_"):
            continue

        with pytest.raises(subprocess.CalledProcessError):
            getattr(tls_manager, method)()

    with pytest.raises(subprocess.CalledProcessError):
        tls_manager.remove_cert("some-alias")


def test_peer_cluster_trust(tls_manager: TLSManager):
    _set_manager_state(tls_manager)
    tls_manager.state.roles = "broker"
    tls_data = generate_tls_artifacts(subject="controller/0")

    tls_manager.state.peer_cluster_ca = [tls_data.ca]
    tls_manager.update_peer_cluster_trust()

    trusted_certs = tls_manager.peer_trusted_certificates
    assert f"{tls_manager.PEER_CLUSTER_ALIAS}0" in trusted_certs
    assert len(trusted_certs) == 1
    fingerprint = next(iter(trusted_certs.values()))

    # expect no-op here
    tls_manager.update_peer_cluster_trust()
    assert len(tls_manager.peer_trusted_certificates) == 1

    # Now let's rotate
    new_tls_data = generate_tls_artifacts(subject="controller/0")
    tls_manager.state.peer_cluster_ca = [new_tls_data.ca]

    tls_manager.update_peer_cluster_trust()
    trusted_certs = tls_manager.peer_trusted_certificates
    # we should have both certificates
    assert f"{tls_manager.PEER_CLUSTER_ALIAS}0" in trusted_certs
    assert f"{tls_manager.NEW_PREFIX}{tls_manager.PEER_CLUSTER_ALIAS}0" in trusted_certs
    assert len(trusted_certs) == 2
    assert fingerprint in tls_manager.peer_trusted_certificates.values()
