#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka TLS configuration."""

import logging
import re
import socket
import subprocess
from typing import TypedDict  # nosec B404

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from ops.pebble import ExecError

from core.cluster import ClusterState
from core.structured_config import CharmConfig
from core.workload import WorkloadBase
from literals import GROUP, USER_NAME, Substrates

logger = logging.getLogger(__name__)

Sans = TypedDict("Sans", {"sans_ip": list[str], "sans_dns": list[str]})


class TLSManager:
    """Manager for building necessary files for Java TLS auth."""

    DEFAULT_HASH_ALGORITHM: hashes.HashAlgorithm = hashes.SHA256()

    def __init__(
        self,
        state: ClusterState,
        workload: WorkloadBase,
        substrate: Substrates,
        config: CharmConfig,
    ):
        self.state = state
        self.workload = workload
        self.substrate = substrate
        self.config = config

        self.keytool = "charmed-kafka.keytool" if self.substrate == "vm" else "keytool"

    def set_server_key(self) -> None:
        """Sets the unit private-key."""
        if not self.state.unit_broker.private_key:
            logger.error("Can't set private-key to unit, missing private-key in relation data")
            return

        self.workload.write(
            content=self.state.unit_broker.private_key,
            path=f"{self.workload.paths.conf_path}/server.key",
        )

    def set_ca(self) -> None:
        """Sets the unit ca."""
        if not self.state.unit_broker.ca:
            logger.error("Can't set CA to unit, missing CA in relation data")
            return

        self.workload.write(
            content=self.state.unit_broker.ca, path=f"{self.workload.paths.conf_path}/ca.pem"
        )

    def set_certificate(self) -> None:
        """Sets the unit certificate."""
        if not self.state.unit_broker.certificate:
            logger.error("Can't set certificate to unit, missing certificate in relation data")
            return

        self.workload.write(
            content=self.state.unit_broker.certificate,
            path=f"{self.workload.paths.conf_path}/server.pem",
        )

    def set_bundle(self) -> None:
        """Sets the unit cert bundle."""
        if not self.state.unit_broker.certificate or not self.state.unit_broker.ca:
            logger.error(
                "Can't set cert bundle to unit, missing certificate or CA in relation data"
            )
            return

        self.workload.write(
            content="\n".join(self.state.unit_broker.bundle),
            path=f"{self.workload.paths.conf_path}/bundle.pem",
        )

    def set_chain(self) -> None:
        """Sets the unit chain."""
        if not self.state.unit_broker.bundle:
            logger.error("Can't set chain to unit, missing chain in relation data")
            return

        # setting each individual cert in the chain for trusting
        for i, chain_cert in enumerate(self.state.unit_broker.bundle):
            self.workload.write(
                content=chain_cert, path=f"{self.workload.paths.conf_path}/bundle{i}.pem"
            )

    def set_truststore(self) -> None:
        """Adds CA to JKS truststore."""
        trust_aliases = [f"bundle{i}" for i in range(len(self.state.unit_broker.bundle))]
        for alias in trust_aliases:
            command = f"{self.keytool} -import -v -alias {alias} -file {alias}.pem -keystore truststore.jks -storepass {self.state.unit_broker.truststore_password} -noprompt"
            try:

                self.workload.exec(
                    command=command.split(), working_dir=self.workload.paths.conf_path
                )
                self.workload.exec(
                    f"chown {USER_NAME}:{GROUP} {self.workload.paths.truststore}".split()
                )
                self.workload.exec(f"chmod 770 {self.workload.paths.truststore}".split())
            except (subprocess.CalledProcessError, ExecError) as e:
                # in case this reruns and fails
                if e.stdout and "already exists" in e.stdout:
                    continue
                logger.error(e.stdout)
                raise e

    def set_keystore(self) -> None:
        """Creates and adds unit cert and private-key to the keystore."""
        if not (
            all(
                [
                    self.state.unit_broker.private_key,
                    self.state.unit_broker.certificate,
                    self.state.unit_broker.ca,
                ]
            )
        ):
            logger.error("Can't set keystore, missing TLS artifacts.")
            return

        command = f"openssl pkcs12 -export -in bundle.pem -inkey server.key -passin pass:{self.state.unit_broker.keystore_password} -certfile server.pem -out keystore.p12 -password pass:{self.state.unit_broker.keystore_password}"

        try:
            self.workload.exec(command=command.split(), working_dir=self.workload.paths.conf_path)
            self.workload.exec(f"chown {USER_NAME}:{GROUP} {self.workload.paths.keystore}".split())
            self.workload.exec(f"chmod 770 {self.workload.paths.keystore}".split())
        except (subprocess.CalledProcessError, ExecError) as e:
            logger.error(e.stdout)
            raise e

    def import_cert(self, alias: str, filename: str) -> None:
        """Add a certificate to the truststore."""
        command = f"{self.keytool} -import -v -alias {alias} -file {filename} -keystore truststore.jks -storepass {self.state.unit_broker.truststore_password} -noprompt"
        try:
            self.workload.exec(command=command.split(), working_dir=self.workload.paths.conf_path)
        except (subprocess.CalledProcessError, ExecError) as e:
            # in case this reruns and fails
            if e.stdout and "already exists" in e.stdout:
                logger.debug(e.stdout)
                return
            logger.error(e.stdout)
            raise e

    def remove_cert(self, alias: str) -> None:
        """Remove a cert from the truststore."""
        try:
            command = f"{self.keytool} -delete -v -alias {alias} -keystore truststore.jks -storepass {self.state.unit_broker.truststore_password} -noprompt"
            self.workload.exec(command=command.split(), working_dir=self.workload.paths.conf_path)
            self.workload.exec(
                f"rm -f {alias}.pem".split(), working_dir=self.workload.paths.conf_path
            )
        except (subprocess.CalledProcessError, ExecError) as e:
            if e.stdout and "does not exist" in e.stdout:
                logger.warning(e.stdout)
                return
            logger.error(e.stdout)
            raise e

    def update_cert(self, alias: str, cert: str) -> None:
        """Update a certificate in the truststore."""
        # we should remove the previous cert first. If it doesn't exist, it will not raise an error.
        self.remove_cert(alias=alias)
        filename = f"{alias}.pem"
        self.workload.write(content=cert, path=f"{self.workload.paths.conf_path}/{filename}")
        self.import_cert(alias=f"{alias}", filename=filename)

    def alias_needs_update(self, alias: str, cert: str) -> bool:
        """Checks whether an alias in the truststore requires update based on the provided certificate."""
        if not cert:
            return False

        return self.certificate_fingerprint(cert) != self.trusted_certificates.get(alias, b"")

    def _build_extra_sans(self) -> list[str]:
        """Parse the certificate_extra_sans config option."""
        extra_sans = self.config.extra_listeners or self.config.certificate_extra_sans or []
        clean_sans = [san.split(":")[0] for san in extra_sans]
        parsed_sans = [
            san.replace("{unit}", str(self.state.unit_broker.unit_id)) for san in clean_sans
        ]

        return parsed_sans

    def build_sans(self) -> Sans:
        """Builds a SAN dict of DNS names and IPs for the unit."""
        if self.substrate == "vm":
            return {
                "sans_ip": [
                    self.state.unit_broker.internal_address,
                ],
                "sans_dns": [self.state.unit_broker.unit.name, socket.getfqdn()]
                + self._build_extra_sans(),
            }
        else:
            return {
                "sans_ip": sorted(
                    [
                        str(self.state.bind_address),
                        self.state.unit_broker.node_ip,
                    ]
                ),
                "sans_dns": sorted(
                    [
                        self.state.unit_broker.internal_address.split(".")[0],
                        self.state.unit_broker.internal_address,
                        socket.getfqdn(),
                    ]
                    + self._build_extra_sans()
                ),
            }

    def get_current_sans(self) -> Sans | None:
        """Gets the current SANs for the unit cert."""
        if not self.state.unit_broker.certificate:
            return

        command = ["openssl", "x509", "-noout", "-ext", "subjectAltName", "-in", "server.pem"]

        try:
            sans_lines = self.workload.exec(
                command=command, working_dir=self.workload.paths.conf_path
            ).splitlines()
        except (subprocess.CalledProcessError, ExecError) as e:
            logger.error(e.stdout)
            raise e

        if not sans_lines:
            return

        for line in sans_lines:
            if "DNS" in line and "IP" in line:
                break

        sans_ip = []
        sans_dns = []
        for item in line.split(", "):
            san_type, san_value = item.split(":")

            if san_type.strip() == "DNS":
                sans_dns.append(san_value)
            if san_type.strip() == "IP Address":
                sans_ip.append(san_value)

        return {"sans_ip": sorted(sans_ip), "sans_dns": sorted(sans_dns)}

    def remove_stores(self) -> None:
        """Cleans up all keys/certs/stores on a unit."""
        for pattern in ["*.pem", "*.key", "*.p12", "*.jks"]:
            for path in (self.workload.root / self.workload.paths.conf_path).glob(pattern):
                path.unlink()

    def reload_truststore(self) -> None:
        """Reloads the truststore using `kafka-configs` utility without restarting the broker."""
        if (
            not (self.workload.root / self.workload.paths.client_properties).exists()
            or not (self.workload.root / self.workload.paths.truststore).exists()
        ):
            # Too soon, return
            return

        bin_args = [
            f"--command-config {self.workload.paths.client_properties}",
            f"--bootstrap-server {self.state.bootstrap_server_internal}",
            "--entity-type brokers",
            f"--entity-name {self.state.kraft_unit_id}",
            "--alter",
            f"--add-config listener.name.CLIENT_SSL_SSL.ssl.truststore.location={self.workload.paths.truststore}",
        ]

        logger.info("Reloading truststore")
        self.workload.run_bin_command(
            bin_keyword="configs",
            bin_args=bin_args,
        )

    def alias_common_name(self, alias: str) -> str:
        """Returns the common name for a loaded certificate alias."""
        if alias not in self.trusted_certificates:
            raise Exception(f"{alias=} can't be found in the truststore.")

        cert = "\n".join(self.workload.read(f"{self.workload.paths.conf_path}/{alias}.pem"))
        if not cert:
            raise FileNotFoundError(f"Can't find the certificate for {alias=}")

        return self.certificate_common_name(cert)

    @staticmethod
    def is_valid_leaf_certificate(cert: str) -> bool:
        """Validates if `cert` is a valid leaf certificate (not a CA)."""
        # split the certificates by the end of the certificate marker and keep the marker in the cert
        raw_cas = cert.split("-----END CERTIFICATE-----")
        # add the marker back to the certificate
        leaf_cert = raw_cas[0].strip() + "\n-----END CERTIFICATE-----"
        certificate = x509.load_pem_x509_certificate(data=leaf_cert.encode())
        # check if the certificate is a CA
        try:
            basic_constraints = certificate.extensions.get_extension_for_class(
                x509.BasicConstraints
            ).value
        except x509.ExtensionNotFound:
            return True
        # check if the certificate can sign other certificates
        try:
            key_usage = certificate.extensions.get_extension_for_class(x509.KeyUsage).value
        except x509.ExtensionNotFound:
            return not basic_constraints.ca

        return not (key_usage.key_cert_sign or key_usage.crl_sign or basic_constraints.ca)

    @staticmethod
    def certificate_common_name(cert: str) -> str:
        """Returns the certificate Common Name (CN)."""
        cert_obj = x509.load_pem_x509_certificate(cert.encode("utf-8"), default_backend())
        return cert_obj.subject.rfc4514_string()

    @staticmethod
    def certificate_fingerprint(cert: str):
        """Returns the certificate fingerprint using SHA-256 algorithm."""
        cert_obj = x509.load_pem_x509_certificate(cert.encode("utf-8"), default_backend())
        hash_algorithm = cert_obj.signature_hash_algorithm or TLSManager.DEFAULT_HASH_ALGORITHM
        return cert_obj.fingerprint(hash_algorithm)

    @staticmethod
    def keytool_hash_to_bytes(hash: str) -> bytes:
        """Converts a hash in the keytool format (AB:CD:0F:...) to a bytes object."""
        return bytes([int(s, 16) for s in hash.split(":")])

    @property
    def trusted_certificates(self) -> dict[str, bytes]:
        """Returns a mapping of alias to certificate fingerprint (hash) for all the certificates loaded in the truststore."""
        if not (self.workload.root / self.workload.paths.truststore).exists():
            return {}

        command = f"{self.keytool} -list -keystore truststore.jks -storepass {self.state.unit_broker.truststore_password} -noprompt"
        raw = self.workload.exec(
            command=command.split(), working_dir=self.workload.paths.conf_path
        )

        # each record in the truststore has the following format:
        #
        # May DD, YYYY, trustedCertEntry,
        # Certificate fingerprint (SHA-256): E5:2E:...:EB:F3
        #
        # SHA-256 is 32 bytes, so the hash would be 64 hex chars + 31 colons = 95 chars
        return {
            match[0]: self.keytool_hash_to_bytes(match[1])
            for match in re.findall("(.+?),.+?trustedCertEntry.*?\n.+?([0-9a-fA-F:]{95})\n", raw)
        }
