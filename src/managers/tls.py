#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka TLS configuration."""

import logging
import socket
import subprocess
from typing import TypedDict  # nosec B404

from ops.pebble import ExecError

from core.cluster import ClusterState
from core.structured_config import CharmConfig
from core.workload import WorkloadBase
from literals import GROUP, USER, Substrates

logger = logging.getLogger(__name__)

Sans = TypedDict("Sans", {"sans_ip": list[str], "sans_dns": list[str]})


class TLSManager:
    """Manager for building necessary files for Java TLS auth."""

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

    def generate_alias(self, app_name: str, relation_id: int) -> str:
        """Generate an alias from a relation. Used to identify ca certs."""
        return f"{app_name}-{relation_id}"

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

    def set_chain(self) -> None:
        """Sets the unit chain."""
        if not self.state.unit_broker.chain:
            logger.error("Can't set chain to unit, missing chain in relation data")
            return

        for i, chain_cert in enumerate(self.state.unit_broker.chain):
            self.workload.write(
                content=chain_cert, path=f"{self.workload.paths.conf_path}/chain{i}.pem"
            )

    def set_truststore(self) -> None:
        """Adds CA to JKS truststore."""
        trust_aliases = [f"chain{i}" for i in range(len(self.state.unit_broker.chain))] + ["ca"]
        for alias in trust_aliases:
            command = f"{self.keytool} -import -v -alias {alias} -file {alias}.pem -keystore truststore.jks -storepass {self.state.unit_broker.truststore_password} -noprompt"
            try:

                self.workload.exec(
                    command=command.split(), working_dir=self.workload.paths.conf_path
                )
                self.workload.exec(
                    f"chown {USER}:{GROUP} {self.workload.paths.truststore}".split()
                )
                self.workload.exec(f"chmod 770 {self.workload.paths.truststore}".split())
            except (subprocess.CalledProcessError, ExecError) as e:
                # in case this reruns and fails
                if e.stdout and "already exists" in e.stdout:
                    return
                logger.error(e.stdout)
                raise e

    def set_keystore(self) -> None:
        """Creates and adds unit cert and private-key to the keystore."""
        command = f"openssl pkcs12 -export -in server.pem -inkey server.key -passin pass:{self.state.unit_broker.keystore_password} -certfile server.pem -out keystore.p12 -password pass:{self.state.unit_broker.keystore_password}"
        try:
            self.workload.exec(command=command.split(), working_dir=self.workload.paths.conf_path)
            self.workload.exec(f"chown {USER}:{GROUP} {self.workload.paths.keystore}".split())
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
        try:
            self.workload.exec(
                command=["rm", "-rf", "*.pem", "*.key", "*.p12", "*.jks"],
                working_dir=self.workload.paths.conf_path,
            )
        except (subprocess.CalledProcessError, ExecError) as e:
            logger.error(e.stdout)
            raise e

    def reload_truststore(self) -> None:
        """Reloads the truststore using `kafka-configs` utility without restarting the broker."""
        bin_args = [
            f"--command-config {self.workload.paths.client_properties}",
            f"--bootstrap-server {self.state.bootstrap_server_internal}",
            "--entity-type brokers",
            f"--entity-name {self.state.unit_broker.unit_id}",
            "--alter",
            f"--add-config listener.name.CLIENT_SSL_SSL.ssl.truststore.location={self.workload.paths.truststore}",
        ]

        logger.info("Reloading truststore")
        self.workload.run_bin_command(
            bin_keyword="configs",
            bin_args=bin_args,
        )
