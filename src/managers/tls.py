#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka TLS configuration."""

import logging
import re
import socket
import subprocess
from datetime import timedelta
from typing import TypedDict  # nosec B404

from charms.tls_certificates_interface.v4.tls_certificates import (
    PrivateKey,
    generate_ca,
    generate_certificate,
    generate_csr,
    generate_private_key,
)
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from ops.pebble import ExecError

from core.cluster import ClusterState
from core.models import GeneratedCa, SelfSignedCertificate, TLSScope, TLSState
from core.structured_config import CharmConfig
from core.workload import WorkloadBase
from literals import GROUP, USER_NAME, Substrates

logger = logging.getLogger(__name__)

Sans = TypedDict("Sans", {"sans_ip": list[str], "sans_dns": list[str]})


class UnknownScopeError(Exception):
    """Exception raised when TLS scope is undefined or not implemented."""


class TLSManager:
    """Manager for building necessary files for Java TLS auth."""

    DEFAULT_HASH_ALGORITHM: hashes.HashAlgorithm = hashes.SHA256()
    SCOPES = (TLSScope.PEER, TLSScope.CLIENT)
    TEMP_ALIAS_PREFIX = "new-"
    PEER_CLUSTER_ALIAS = "cluster-tls"

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

    def get_state(self, scope: TLSScope) -> TLSState:
        """Returns the TLSState object for the given scope."""
        if scope == TLSScope.PEER:
            return self.state.unit_broker.peer_certs
        elif scope == TLSScope.CLIENT:
            return self.state.unit_broker.client_certs

        raise UnknownScopeError(f"Unknown scope: {scope}")

    def get_truststore_path(self, scope: TLSScope) -> str:
        """Returns the truststore path for the given scope."""
        if scope == TLSScope.PEER:
            return self.workload.paths.peer_truststore
        elif scope == TLSScope.CLIENT:
            return self.workload.paths.truststore

        raise UnknownScopeError(f"Unknown scope: {scope}")

    def get_keystore_path(self, scope: TLSScope) -> str:
        """Returns the keystore path for the given scope."""
        if scope == TLSScope.PEER:
            return self.workload.paths.peer_keystore
        elif scope == TLSScope.CLIENT:
            return self.workload.paths.keystore

        raise UnknownScopeError(f"Unknown scope: {scope}")

    def generate_internal_ca(self) -> GeneratedCa:
        """Set up internal CA to issue self-signed certificates for internal communications."""
        ca_key = generate_private_key()
        ca = generate_ca(
            private_key=ca_key,
            validity=timedelta(days=3650),
            common_name=f"{self.state.unit_broker.unit.app.name}",
            organization=TLSScope.PEER.value,
        )

        return GeneratedCa(ca=ca.raw, ca_key=ca_key.raw)

    def generate_self_signed_certificate(self) -> SelfSignedCertificate | None:
        """Generate self-signed certificate for the unit to be used for internal communications."""
        state = self.get_state(TLSScope.PEER)

        if not self.state.internal_ca:
            logger.error("Internal CA is not set up yet.")
            return

        if state.ready:
            logger.debug("No need to set up internal credentials...")
            return

        ca_key, ca = self.state.internal_ca_key, self.state.internal_ca
        if ca is None or ca_key is None:
            logger.error("Internal CA is not setup yet.")
            return

        private_key = (
            PrivateKey(state.private_key) if state.private_key else generate_private_key()
        )

        # Generate CSR & cert
        sans = self.build_sans()
        csr = generate_csr(
            private_key=private_key,
            common_name=f"{self.state.unit_broker.unit.name}",
            sans_ip=frozenset(sans["sans_ip"]),
            sans_dns=frozenset(sans["sans_dns"]),
        )
        certificate = generate_certificate(
            csr=csr, ca=ca, ca_private_key=ca_key, validity=timedelta(days=3650)
        )

        return SelfSignedCertificate(
            ca=ca.raw, csr=csr.raw, certificate=certificate.raw, private_key=private_key.raw
        )

    def set_server_key(self) -> None:
        """Sets the unit private-key."""
        for scope in self.SCOPES:
            state = self.get_state(scope)

            if not state.private_key:
                logger.debug("Can't set private-key to unit, missing private-key in relation data")
                continue

            self.workload.write(
                content=state.private_key,
                path=f"{self.workload.paths.conf_path}/{scope.value}-server.key",
            )

    def set_ca(self) -> None:
        """Sets the unit ca."""
        for scope in self.SCOPES:
            state = self.get_state(scope)

            if not state.ca:
                logger.debug("Can't set CA to unit, missing CA in relation data")
                continue

            self.workload.write(
                content=state.ca, path=f"{self.workload.paths.conf_path}/{scope.value}-ca.pem"
            )

    def set_certificate(self) -> None:
        """Sets the unit certificate."""
        for scope in self.SCOPES:
            state = self.get_state(scope)

            if not state.certificate:
                logger.debug("Can't set certificate to unit, missing certificate in relation data")
                continue

            self.workload.write(
                content=state.certificate,
                path=f"{self.workload.paths.conf_path}/{scope.value}-server.pem",
            )

    def set_bundle(self) -> None:
        """Sets the unit cert bundle."""
        for scope in self.SCOPES:
            state = self.get_state(scope)

            if not state.certificate or not state.ca:
                logger.debug(
                    "Can't set cert bundle to unit, missing certificate or CA in relation data"
                )
                continue

            self.workload.write(
                content="\n".join(state.bundle),
                path=f"{self.workload.paths.conf_path}/{scope.value}-bundle.pem",
            )

    def set_chain(self) -> None:
        """Sets the unit chain."""
        for scope in self.SCOPES:
            state = self.get_state(scope)

            if not state.bundle:
                logger.debug("Can't set chain to unit, missing chain in relation data")
                continue

            # setting each individual cert in the chain for trusting
            for i, chain_cert in enumerate(state.bundle):
                self.workload.write(
                    content=chain_cert,
                    path=f"{self.workload.paths.conf_path}/{scope.value}-bundle{i}.pem",
                )

    def set_truststore(self) -> None:
        """Adds CA to JKS truststore."""
        for scope in self.SCOPES:
            state = self.get_state(scope)

            trust_aliases = [f"bundle{i}" for i in range(len(state.bundle))]
            for alias in trust_aliases:
                command = [
                    self.keytool,
                    "-import",
                    "-v",
                    "-alias",
                    alias,
                    "-file",
                    f"{scope.value}-{alias}.pem",
                    "-keystore",
                    f"{scope.value}-truststore.jks",
                    "-storepass",
                    f"{self.state.unit_broker.truststore_password}",
                    "-noprompt",
                ]
                try:
                    self.workload.exec(command=command, working_dir=self.workload.paths.conf_path)
                    self.workload.exec(
                        f"chown {USER_NAME}:{GROUP} {self.get_truststore_path(scope)}".split()
                    )
                    self.workload.exec(f"chmod 770 {self.get_truststore_path(scope)}".split())
                except (subprocess.CalledProcessError, ExecError) as e:
                    # in case this reruns and fails
                    if e.stdout and "already exists" in e.stdout:
                        continue
                    logger.error(e.stdout)
                    raise e

    def set_keystore(self) -> None:
        """Creates and adds unit cert and private-key to the keystore."""
        for scope in self.SCOPES:
            state = self.get_state(scope)

            if not all([state.private_key, state.certificate, state.ca]):
                logger.debug("Can't set keystore, missing TLS artifacts.")
                continue

            command = [
                "openssl",
                "pkcs12",
                "-export",
                "-in",
                f"{scope.value}-bundle.pem",
                "-inkey",
                f"{scope.value}-server.key",
                "-passin",
                f"pass:{self.state.unit_broker.keystore_password}",
                "-certfile",
                f"{scope.value}-server.pem",
                "-out",
                f"{scope.value}-keystore.p12",
                "-password",
                f"pass:{self.state.unit_broker.keystore_password}",
            ]

            try:
                self.workload.exec(command=command, working_dir=self.workload.paths.conf_path)
                self.workload.exec(
                    f"chown {USER_NAME}:{GROUP} {self.get_keystore_path(scope)}".split()
                )
                self.workload.exec(f"chmod 770 {self.get_keystore_path(scope)}".split())
            except (subprocess.CalledProcessError, ExecError) as e:
                logger.error(e.stdout)
                raise e

    def update_peer_cluster_trust(self) -> None:
        """Updates peer truststore with current state of peer-cluster certificate chain.

        This method will toggle the TLS rotation state variable if certificate change is detected in the peer-cluster relationship.
        """
        bundle = self.state.peer_cluster_ca
        state = self.get_state(TLSScope.PEER)

        if not bundle:
            return

        trusted_certs = self.peer_trusted_certificates
        for i, cert in enumerate(bundle):
            if self.certificate_fingerprint(cert) in trusted_certs.values():
                continue

            alias = f"{self.PEER_CLUSTER_ALIAS}{i}"
            state.rotate = True

            self.update_cert(alias=alias, cert=cert, scope=TLSScope.PEER)

    def configure(self) -> None:
        """Write all TLS artifacts including certs, keys, and keystores/truststores to the disk."""
        self.set_server_key()
        self.set_ca()
        self.set_chain()
        self.set_certificate()
        self.set_bundle()
        self.set_truststore()
        self.set_keystore()
        self.update_peer_cluster_trust()

    def import_cert(self, alias: str, filename: str, scope: TLSScope = TLSScope.CLIENT) -> None:
        """Add a certificate to the truststore."""
        command = [
            self.keytool,
            "-import",
            "-v",
            "-alias",
            alias,
            "-file",
            filename,
            "-keystore",
            f"{scope.value}-truststore.jks",
            "-storepass",
            f"{self.state.unit_broker.truststore_password}",
            "-noprompt",
        ]
        try:
            self.workload.exec(command=command, working_dir=self.workload.paths.conf_path)
        except (subprocess.CalledProcessError, ExecError) as e:
            # in case this reruns and fails
            if e.stdout and "already exists" in e.stdout:
                logger.debug(e.stdout)
                return
            logger.error(e.stdout)
            raise e

    def remove_cert(self, alias: str, scope: TLSScope = TLSScope.CLIENT) -> None:
        """Remove a cert from the truststore."""
        try:
            command = [
                self.keytool,
                "-delete",
                "-v",
                "-alias",
                alias,
                "-keystore",
                f"{scope.value}-truststore.jks",
                "-storepass",
                f"{self.state.unit_broker.truststore_password}",
                "-noprompt",
            ]
            self.workload.exec(command=command, working_dir=self.workload.paths.conf_path)
            self.workload.exec(
                f"rm -f {scope.value}-{alias}.pem".split(),
                working_dir=self.workload.paths.conf_path,
            )
        except (subprocess.CalledProcessError, ExecError) as e:
            if e.stdout and "does not exist" in e.stdout:
                logger.debug(e.stdout)
                return
            logger.error(e.stdout)
            raise e

    def update_cert(self, alias: str, cert: str, scope: TLSScope = TLSScope.CLIENT) -> None:
        """Update a certificate in the truststore."""
        # we should remove the previous cert first. If it doesn't exist, it will not raise an error.
        self.remove_cert(alias=alias, scope=scope)
        filename = f"{scope.value}-{alias}.pem"
        self.workload.write(content=cert, path=f"{self.workload.paths.conf_path}/{filename}")
        self.import_cert(alias=alias, filename=filename, scope=scope)

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

    def get_current_sans(self, scope: TLSScope = TLSScope.CLIENT) -> Sans | None:
        """Gets the current SANs for the unit cert."""
        state = self.get_state(scope)
        if (
            not state.certificate
            or not (
                self.workload.root / self.workload.paths.conf_path / f"{scope.value}-server.pem"
            ).exists()
        ):
            return

        command = [
            "openssl",
            "x509",
            "-noout",
            "-ext",
            "subjectAltName",
            "-in",
            f"{scope.value}-server.pem",
        ]

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

    def remove_stores(self, scope: TLSScope = TLSScope.CLIENT) -> None:
        """Cleans up all keys/certs/stores on a unit."""
        for pattern in ["*.pem", "*.key", "*.p12", "*.jks"]:
            for path in (self.workload.root / self.workload.paths.conf_path).glob(
                f"{scope.value}-{pattern}"
            ):
                logger.debug(f"Removing {path}")
                path.unlink()

    def reload_truststore(self) -> None:
        """Reloads the truststore using `kafka-configs` utility without restarting the broker."""
        if not (
            all(
                [
                    (self.workload.root / self.workload.paths.truststore).exists(),
                    (self.workload.root / self.workload.paths.client_properties).exists(),
                ]
            )
        ):
            return

        bin_args = [
            f"--command-config {self.workload.paths.client_properties}",
            f"--bootstrap-server {self.state.bootstrap_server_internal}",
            "--entity-type brokers",
            f"--entity-name {self.state.unit_broker.broker_id}",
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

        cert = "\n".join(
            self.workload.read(
                f"{self.workload.paths.conf_path}/{TLSScope.CLIENT.value}-{alias}.pem"
            )
        )
        if not cert:
            raise FileNotFoundError(f"Can't find the certificate for {alias=}")

        return self.certificate_distinguished_name(cert)

    def get_trusted_certificates(self, truststore_path: str) -> dict[str, bytes]:
        """Returns a mapping of alias to certificate fingerprint (hash) for all the certificates loaded in the given truststore."""
        if not (self.workload.root / truststore_path).exists():
            return {}

        command = [
            self.keytool,
            "-list",
            "-keystore",
            truststore_path,
            "-storepass",
            self.state.unit_broker.truststore_password,
            "-noprompt",
        ]
        raw = self.workload.exec(command=command, working_dir=self.workload.paths.conf_path)

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
    def certificate_distinguished_name(cert: str) -> str:
        """Returns the certificate distinguished name."""
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
        """Returns a mapping of alias to certificate fingerprint (hash) for all the certificates loaded in the CLIENT truststore."""
        return self.get_trusted_certificates(self.workload.paths.truststore)

    @property
    def peer_trusted_certificates(self) -> dict[str, bytes]:
        """Returns a mapping of alias to certificate fingerprint (hash) for all the certificates loaded in the PEER truststore."""
        return self.get_trusted_certificates(self.workload.paths.peer_truststore)
