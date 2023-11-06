#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka TLS configuration."""

import logging
import secrets
import socket
import string
import subprocess
from typing import Dict, List

from new.common.workload import IOMode
from new.core.models import KafkaConfig, ClusterRelation
from new.core.workload import AbstractKafkaService, KafkaEntrypoint

logger = logging.getLogger(__name__)


class CertificatesManager:

    def __init__(self,
                 charm_config: KafkaConfig, cluster: ClusterRelation,
                 workload: AbstractKafkaService
                 ):
        self.charm_config = charm_config
        self.cluster = cluster
        self.workload = workload

    @property
    def _extra_sans(self) -> List[str]:
        """Parse the certificate_extra_sans config option."""
        extra_sans = self.charm_config.certificate_extra_sans or ""
        parsed_sans = []

        if extra_sans == "":
            return parsed_sans

        for sans in extra_sans.split(","):
            parsed_sans.append(sans.replace("{unit}", str(self.cluster.unit.unit)))

        return parsed_sans

    @property
    def sans(self) -> Dict[str, List[str]]:
        """Builds a SAN dict of DNS names and IPs for the unit."""
        return {
            "sans_ip": [self.cluster.unit.address],
            "sans_dns": [self.cluster.unit.host, socket.getfqdn()] + self._extra_sans,
        }

    @staticmethod
    def generate_password() -> str:
        """Creates randomized string for use as app passwords.

        Returns:
            String of 32 randomized letter+digit characters
        """
        return "".join([secrets.choice(string.ascii_letters + string.digits) for _ in range(32)])

    @staticmethod
    def generate_alias(app_name: str, relation_id: int) -> str:
        """Generate an alias from a relation. Used to identify ca certs."""
        return f"{app_name}-{relation_id}"

    def set_server_key(self) -> None:
        """Sets the unit private-key."""
        if not self.cluster.tls.private_key:
            logger.error("Can't set private-key to unit, missing private-key in relation data")
            return

        with self.workload.write.server_key as fid:
            fid.write(self.cluster.tls.private_key)

    def set_ca(self) -> None:
        """Sets the unit ca."""
        if not self.cluster.tls.ca:
            logger.error("Can't set CA to unit, missing CA in relation data")
            return

        with self.workload.write.ca as fid:
            fid.write(self.cluster.tls.ca)

    def set_certificate(self) -> None:
        """Sets the unit certificate."""
        if not self.cluster.tls.certificate:
            logger.error("Can't set certificate to unit, missing certificate in relation data")
            return

        with self.workload.write.certificate as fid:
            fid.write(self.cluster.tls.certificate)

    def set_truststore(self) -> None:
        """Adds CA to JKS truststore."""
        try:
            self.workload.exec(
                KafkaEntrypoint.KEYTOOL,
                args=[
                    "-import", "-v", "-alias", "ca", "-file",
                    "-keystore", self.workload.paths.truststore,
                    "-storepass", self.cluster.tls.truststore_password, "-noprompt"
                ]
            )
            self.workload.exec(
                KafkaEntrypoint.CMD,
                args=[
                    "chown", f"{self.workload.user.name}:{self.workload.user.group}",
                    self.workload.paths.truststore
                ]
            )
            self.workload.exec(
                KafkaEntrypoint.CMD,
                args=[
                    "chmod", "770",
                    self.workload.paths.truststore
                ]
            )
        except subprocess.CalledProcessError as e:
            # in case this reruns and fails
            if "already exists" in e.output:
                return
            logger.error(e.output)
            raise e

    def set_keystore(self) -> None:
        """Creates and adds unit cert and private-key to the keystore."""
        try:
            self.workload.exec(
                KafkaEntrypoint.CMD,
                args=[
                    "openssl",
                    "pkcs12",
                    "-export",
                    "-in",
                    self.workload.paths.certificate,
                    "-inkey",
                    self.workload.paths.server_key,
                    "-passin",
                    f"pass:{self.cluster.tls.keystore_password}",
                    "-certfile",
                    self.workload.paths.certificate,
                    "-out",
                    self.workload.paths.keystore,
                    "-password",
                    f"pass:{self.cluster.tls.keystore_password}",
                ],
                working_dir=self.workload.paths.CONF_PATH
            )
            self.workload.exec(
                KafkaEntrypoint.CMD,
                args=[
                    "chown", f"{self.workload.user.name}:{self.workload.user.group}",
                    self.workload.paths.keystore
                ]
            )
            self.workload.exec(
                KafkaEntrypoint.CMD,
                args=[
                    "chmod", "770",
                    self.workload.paths.keystore
                ]
            )
        except subprocess.CalledProcessError as e:
            logger.error(e.output)
            raise e

    def import_cert(self, alias: str, content: str) -> None:
        """Add a certificate to the truststore."""
        try:
            filename = f"{self.workload.paths.CONF_PATH}/{alias}.pem"
            with self.workload.get_file(filename, IOMode.WRITE) as fid:
                fid.write(content)
            self.workload.exec(
                KafkaEntrypoint.KEYTOOL,
                [
                    "-import", "-v", "-alias", alias, "-file", filename,
                    "-keystore", self.workload.paths.truststore,
                    "-storepass", self.cluster.tls.truststore_password, "-noprompt"
                ]
            )
        except subprocess.CalledProcessError as e:
            # in case this reruns and fails
            if "already exists" in e.output:
                logger.debug(e.output)
                return
            logger.error(e.output)
            raise e

    def remove_cert(self, alias: str) -> None:
        """Remove a cert from the truststore."""
        try:
            self.workload.exec(
                KafkaEntrypoint.KEYTOOL,
                [
                    "-delete", "-v", "-alias", alias,
                    "-keystore", self.workload.paths.truststore,
                    "-storepass", self.cluster.tls.truststore_password, "-noprompt"
                ]
            )
            self.workload.exec(
                KafkaEntrypoint.CMD,
                args=[
                    "rm", "-f", f"{alias}.pem"
                ],
                working_dir=self.workload.paths.CONF_PATH
            )
        except subprocess.CalledProcessError as e:
            if "does not exist" in e.output:
                logger.warning(e.output)
                return
            logger.error(e.output)
            raise e

    def remove_stores(self) -> None:
        """Cleans up all keys/certs/stores on a unit."""
        try:
            self.workload.exec(
                KafkaEntrypoint.CMD,
                args=[
                    "rm", "-rf", "*.pem", "*.key", "*.p12", "*.jks"
                ],
                working_dir=self.workload.paths.CONF_PATH
            )
        except subprocess.CalledProcessError as e:
            logger.error(e.output)
            raise e
