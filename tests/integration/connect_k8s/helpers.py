#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.
import json
import logging
import re
import socket
import ssl
import tempfile
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from subprocess import PIPE, CalledProcessError, check_output
from typing import cast

import requests
import yaml
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.x509 import Certificate, load_pem_x509_certificate
from cryptography.x509.extensions import SubjectAlternativeName
from cryptography.x509.oid import ExtensionOID
from jubilant_adapters import JujuFixture
from jubilant_adapters.adapters import UnitAdapter as Unit
from requests.auth import HTTPBasicAuth
from single_kernel_kafka.core.connect_models import PeerWorkersContext
from single_kernel_kafka.core.literals import ConnectLiterals

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("connect_k8s/metadata.yaml").read_text())
APP_NAME = METADATA["name"]
CONFIG_DIR = "/etc/connect"
DEFAULT_API_PORT = ConnectLiterals.DEFAULT_API_PORT
PLUGIN_RESOURCE_KEY = ConnectLiterals.PLUGIN_RESOURCE_KEY
IMAGE_RESOURCE_KEY = "kafka-image"
IMAGE_URI = METADATA["resources"]["kafka-image"]["upstream-source"]
PASSWORDS_PATH = f"{CONFIG_DIR}/connect.password"
KAFKA_APP = "kafka-k8s"
KAFKA_CHANNEL = "3/edge"
MYSQL_APP = "mysql-k8s"
MYSQL_CHANNEL = "8.0/stable"

JDBC_CONNECTOR_DOWNLOAD_LINK = "https://github.com/Aiven-Open/jdbc-connector-for-apache-kafka/releases/download/v6.10.0/jdbc-connector-for-apache-kafka-6.10.0.tar"
JDBC_SOURCE_CONNECTOR_CLASS = "io.aiven.connect.jdbc.JdbcSourceConnector"
JDBC_SINK_CONNECTOR_CLASS = "io.aiven.connect.jdbc.JdbcSinkConnector"

S3_CONNECTOR_LINK = "https://github.com/Aiven-Open/cloud-storage-connectors-for-apache-kafka/releases/download/v3.1.0/s3-sink-connector-for-apache-kafka-3.1.0.tar"
S3_CONNECTOR_CLASS = "io.aiven.kafka.connect.s3.AivenKafkaConnectS3SinkConnector"


@dataclass
class CommandResult:
    return_code: int | None
    stdout: str
    stderr: str


@dataclass
class DatabaseFixtureParams:
    """Data model for database test data fixture requests."""

    app_name: str
    db_name: str
    no_tables: int = 1
    no_records: int = 1000


def check_socket(host: str | None, port: int) -> bool:
    """Checks whether IPv4 socket is up or not."""
    if host is None:
        return False

    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        return sock.connect_ex((host, port)) == 0


def run_command_on_unit(
    juju: JujuFixture, unit: Unit, command: str | list[str], container: str = "kafka-connect"
) -> CommandResult:
    """Runs a command on a given unit and returns the result."""
    command_args = command.split() if isinstance(command, str) else command
    return_code, stdout, stderr = juju.juju(
        "ssh", "--container", container, f"{unit.name}", *command_args
    )

    return CommandResult(return_code=return_code, stdout=stdout, stderr=stderr)


def get_unit_ipv4_address(juju: JujuFixture, unit: Unit) -> str | None:
    """A safer alternative for `juju.unit.get_public_address()` which is robust to network changes."""
    _, stdout, _ = juju.juju("ssh", f"{unit.name}", "hostname -i")
    ipv4_matches = re.findall(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}", stdout)

    if ipv4_matches:
        return ipv4_matches[0]

    return None


def check_connect_endpoints_status(
    juju: JujuFixture, app_name: str = APP_NAME, port: int = DEFAULT_API_PORT, verbose: bool = True
) -> dict[Unit, bool]:
    """Returns a dict of unit: status mapping where status is True if endpoint is up and False otherwise."""
    status = {}
    units = juju.ext.model.applications[app_name].units

    for unit in units:
        ipv4_address = get_unit_ipv4_address(juju, unit)
        status[unit] = check_socket(ipv4_address, port)

    if verbose:
        print(status)

    return status


def get_admin_password(juju: JujuFixture, unit: Unit) -> str:
    """Get admin user's password of a unit by reading credentials file."""
    res = run_command_on_unit(juju, unit, f"cat {PASSWORDS_PATH}")
    raw = res.stdout.strip().split("\n")

    if not raw:
        raise Exception(f"Unable to read the credentials file on unit {unit.name}.")

    for line in raw:
        if line.startswith(PeerWorkersContext.ADMIN_USERNAME):
            return line.split(":")[-1].strip()

    raise Exception(f"Admin user not defined in the credentials file on unit {unit.name}.")


def make_api_request(
    juju: JujuFixture,
    unit: Unit | None = None,
    method: str = "GET",
    endpoint: str = "",
    proto: str = "http",
    port: int = DEFAULT_API_PORT,
    auth_enabled: bool = True,
    custom_auth: tuple[str, str] | None = None,
    verbose: bool = True,
    **kwargs,
) -> requests.Response:
    """Makes a request to a REST Endpoint and returns the response.

    Args:
        juju (OpsTest): OpsTest object
        unit (Unit, optional): Unit used to make the request; if not supplied, uses the first unit in the Kafka Connect application `APP_NAME`.
        method (str, optional): Request method. Defaults to "GET".
        endpoint (str, optional): API endpoint. Defaults to "".
        proto (str, optional): HTTP Protocol: "http" or "https". Defaults to "http".
        port (int, optional): TCP Port. defaults to `DEFAULT_API_PORT`.
        auth_enabled (bool, optional): Whether should use authentication on the endpoint, defaults to True.
        custom_auth (tuple[str, str], optional): A (username, password) tuple to be used for HTTP Basic authentication.
        verbose (bool, optional): Enable verbose logging. Defaults to True.
        kwargs: Keyword arguments which will be passed to `requests.request` method.

    Returns:
        requests.Response: Response object.
    """
    target_unit = juju.ext.model.applications[APP_NAME].units[0] if unit is None else unit

    unit_ip = get_unit_ipv4_address(juju, target_unit)
    url = f"{proto}://{unit_ip}:{port}/{endpoint}"

    auth = None
    if auth_enabled:
        admin_password = get_admin_password(juju, unit=target_unit)
        auth = (
            HTTPBasicAuth(PeerWorkersContext.ADMIN_USERNAME, admin_password)
            if not custom_auth
            else HTTPBasicAuth(*custom_auth)
        )

    response = requests.request(method, url, auth=auth, **kwargs)

    if verbose:
        print(f"{method} - {url}: {response.content}")

    return response


make_connect_api_request = make_api_request


def download_file(url: str, dst_path: str):
    """Downloads a file from given `url` to `dst_path`."""
    response = requests.get(url, stream=True)
    with open(dst_path, mode="wb") as file:
        for chunk in response.iter_content(chunk_size=10 * 1024):
            file.write(chunk)


def build_mysql_db_init_queries(
    test_db_host: str, test_db_user: str, test_db_pass: str, test_db_name: str
) -> list[str]:
    """Returns a list of queries to initiate a test MySQL database with 1 table and 3 sample entries."""
    raw = f"""CREATE DATABASE {test_db_name};
    CREATE USER '{test_db_user}'@'{test_db_host}' IDENTIFIED BY '{test_db_pass}';
    GRANT ALL PRIVILEGES ON {test_db_name}.* TO '{test_db_user}'@'{test_db_host}' WITH GRANT OPTION;
    CREATE USER '{test_db_user}'@'%' IDENTIFIED BY '{test_db_pass}';
    GRANT ALL PRIVILEGES ON {test_db_name}.* TO '{test_db_user}'@'%' WITH GRANT OPTION;
    CREATE TABLE {test_db_name}.products (
        id int NOT NULL AUTO_INCREMENT,
        name varchar(50) DEFAULT NULL,
        price float DEFAULT NULL,
        created_at timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY product_id_uindex (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
    INSERT INTO {test_db_name}.products (name, price) Values ('p1', 10.0), ('p2', 20.0), ('p3', 30.0);
    """

    queries = [query.strip().replace("\n", " ") for query in raw.split(";")]
    return [query for query in queries if query]


def search_secrets(juju: JujuFixture, owner: str, search_key: str) -> str:
    """Searches secrets for a provided `search_key` and returns it if found, otherwise return empty string."""
    secrets_meta_raw = check_output(
        f"JUJU_MODEL={juju.ext.model_full_name} juju list-secrets --format json",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    ).strip()
    secrets_meta = json.loads(secrets_meta_raw)

    for secret_id in secrets_meta:
        if owner and not secrets_meta[secret_id]["owner"] == owner:
            continue

        secrets_data_raw = check_output(
            f"JUJU_MODEL={juju.ext.model_full_name} juju show-secret --format json --reveal {secret_id}",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )

        secret_data = json.loads(secrets_data_raw)
        if search_key in secret_data[secret_id]["content"]["Data"]:
            return secret_data[secret_id]["content"]["Data"][search_key]

    return ""


def get_certificate(
    juju: JujuFixture, unit: Unit | None = None, port: int = DEFAULT_API_PORT
) -> Certificate:
    """Gets TLS certificate of a particular unit using a socket.

    Args:
        juju (OpsTest): OpsTest object
        unit (Unit | None, optional): Unit used to establish the socket; if not supplied, uses the first unit in the Kafka Connect application `APP_NAME`.
        port (int, optional): Socket port. Defaults to DEFAULT_API_PORT.

    Returns:
        Certificate: Unit's certificate used on the socket.
    """
    target_unit = juju.ext.model.applications[APP_NAME].units[0] if unit is None else unit
    unit_ip = get_unit_ipv4_address(juju, target_unit)

    pem = ssl.get_server_certificate((f"{unit_ip}", port))
    return load_pem_x509_certificate(str.encode(pem), default_backend())


def extract_sans(cert: Certificate) -> list[str]:
    """Returns the list of Subject Alternative Names (SANs) of a given certificate."""
    ext = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
    val = cast(SubjectAlternativeName, ext.value)
    return val.get_values_for_type(x509.DNSName)


@contextmanager
def self_signed_ca(juju: JujuFixture, app_name: str):
    """Returns a context manager with self-signed-certificates operator CA file."""
    action_name: str = "get-ca-certificate"
    unit = juju.ext.model.applications[app_name].units[0]
    action = unit.run_action(action_name=action_name)
    result = action.wait()
    ca = result.results.get("ca-certificate")

    with tempfile.NamedTemporaryFile(mode="w", delete_on_close=False) as ca_file:
        ca_file.write(ca)
        ca_file.close()
        yield ca_file


def destroy_active_workers(juju: JujuFixture):
    status_resp = make_connect_api_request(juju, endpoint="connectors?expand=status")

    workers = {
        item["status"]["connector"]["worker_id"].split(":")[0]
        for item in status_resp.json().values()
    }

    pods = {worker.split(".")[0] for worker in workers}
    for pod in pods:
        delete_pod(juju, pod)


def delete_pod(juju: JujuFixture, pod_name: str):
    check_output(
        f"kubectl delete pod {pod_name} -n {juju.model}",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )


def sign_manual_certs(
    tmp_path: Path, model: str, manual_app: str = "manual-tls-certificates"
) -> str:
    """Sign CSRs using a generated CA, return the path to the CA file."""
    csrs_cmd = [
        f"JUJU_MODEL={model}",
        "juju",
        "run",
        f"{manual_app}/0",
        "get-outstanding-certificate-requests",
        "--format=json",
    ]
    csrs = check_output(" ".join(csrs_cmd), stderr=PIPE, universal_newlines=True, shell=True)
    res = json.loads(csrs)[f"{manual_app}/0"]["results"]["result"]
    csr_list = [i["csr"] for i in json.loads(res)]

    # Generate a CA
    generate_ca_cmd = [
        "openssl",
        "req",
        "-new",
        "-x509",
        "-nodes",
        "-newkey rsa:2048",
        "-keyout ca.key",
        "-out ca.pem",
        "-days 365",
        '-subj "/CN=TestCA"',
        '-addext "basicConstraints=critical,CA:TRUE"',
        '-addext "keyUsage=critical,keyCertSign,cRLSign"',
        '-addext "subjectKeyIdentifier=hash"',
    ]
    check_output(
        " ".join(generate_ca_cmd), stderr=PIPE, universal_newlines=True, shell=True, cwd=tmp_path
    )

    for i, csr in enumerate(csr_list):
        if not csr:
            continue

        tmp_dir = Path(tmp_path)
        csr_file = tmp_dir / f"csr{i}"
        csr_file.write_text(csr)

        cert_file = tmp_dir / f"{i}.pem"

        try:
            sign_cmd = [
                "openssl",
                "x509",
                "-req",
                f"-in {csr_file}",
                f"-CAkey {tmp_path}/ca.key",
                f"-CA {tmp_path}/ca.pem",
                "-days 100",
                "-CAcreateserial",
                f"-out {cert_file}",
                "-copy_extensions",
                "copyall",
            ]
            provide_cmd = [
                f"JUJU_MODEL={model}",
                "juju",
                "run",
                f"{manual_app}/0",
                "provide-certificate",
                f'ca-certificate="$(base64 -w0 {tmp_path}/ca.pem)"',
                f'certificate="$(base64 -w0 {cert_file})"',
                f'certificate-signing-request="$(base64 -w0 {csr_file})"',
            ]

            check_output(" ".join(sign_cmd), stderr=PIPE, universal_newlines=True, shell=True)
            response = check_output(
                " ".join(provide_cmd), stderr=PIPE, universal_newlines=True, shell=True
            )
            logger.info(f"{response=}")
        except CalledProcessError as e:
            logger.error(f"{e.stdout=}, {e.stderr=}, {e.output=}")
            raise e

    return f"{tmp_path}/ca.pem"
