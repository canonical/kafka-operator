# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import tempfile
from enum import Enum
from pathlib import Path
from subprocess import PIPE, CalledProcessError, check_output
from typing import Literal

import yaml

from literals import KRAFT_NODE_ID_OFFSET

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
SERIES = "noble"
CONTROLLER_NAME = "controller"
DUMMY_NAME = "app"
REL_NAME_ADMIN = "kafka-client-admin"
REL_NAME_PRODUCER = "kafka-client-producer"
AUTH_SECRET_CONFIG_KEY = "system-users"
TEST_DEFAULT_MESSAGES = 15
TEST_SECRET_NAME = "auth"


KRaftMode = Literal["single", "multi"]


class KRaftUnitStatus(Enum):
    LEADER = "Leader"
    FOLLOWER = "Follower"
    OBSERVER = "Observer"


logger = logging.getLogger(__name__)


def unit_id_to_broker_id(unit_id: int) -> int:
    """Converts unit id to broker id in KRaft mode."""
    return KRAFT_NODE_ID_OFFSET + unit_id


def broker_id_to_unit_id(broker_id: int) -> int:
    """Converts broker id to unit id in KRaft mode."""
    return broker_id - KRAFT_NODE_ID_OFFSET


def sign_manual_certs(model: str | None, manual_app: str = "manual-tls-certificates") -> None:
    delim = "-----BEGIN CERTIFICATE REQUEST-----"

    csrs_cmd = f"JUJU_MODEL={model} juju run {manual_app}/0 get-outstanding-certificate-requests --format=json | jq -r '.[\"{manual_app}/0\"].results.result' | jq '.[].csr' | sed 's/\\\\n/\\n/g' | sed 's/\\\"//g'"
    csrs = check_output(csrs_cmd, stderr=PIPE, universal_newlines=True, shell=True).split(delim)

    for i, csr in enumerate(csrs):
        if not csr:
            continue

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            csr_file = tmp_dir / f"csr{i}"
            csr_file.write_text(delim + csr)

            cert_file = tmp_dir / f"{i}.pem"

            try:
                sign_cmd = f"openssl x509 -req -in {csr_file} -CAkey tests/integration/data/int.key -CA tests/integration/data/int.pem -days 100 -CAcreateserial -out {cert_file} -copy_extensions copyall --passin pass:password"
                provide_cmd = f'JUJU_MODEL={model} juju run {manual_app}/0 provide-certificate ca-certificate="$(base64 -w0 tests/integration/data/int.pem)" ca-chain="$(base64 -w0 tests/integration/data/root.pem)" certificate="$(base64 -w0 {cert_file})" certificate-signing-request="$(base64 -w0 {csr_file})"'

                check_output(sign_cmd, stderr=PIPE, universal_newlines=True, shell=True)
                response = check_output(
                    provide_cmd, stderr=PIPE, universal_newlines=True, shell=True
                )
                logger.info(f"{response=}")
            except CalledProcessError as e:
                logger.error(f"{e.stdout=}, {e.stderr=}, {e.output=}")
                raise e
