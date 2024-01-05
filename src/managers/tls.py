#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka TLS configuration."""

import logging
import subprocess
from typing import TYPE_CHECKING

from ops.framework import Object


if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)


class TLSManager(Object):
    """TLS Manager implementation."""

    def __init__(self, charm):
        super().__init__(charm, "tls_manager")
        self.charm: "KafkaCharm" = charm

    def generate_alias(self, app_name: str, relation_id: int) -> str:
        """Generate an alias from a relation. Used to identify ca certs."""
        return f"{app_name}-{relation_id}"

    def set_server_key(self) -> None:
        """Sets the unit private-key."""
        if not self.charm.cluster.private_key:
            logger.error("Can't set private-key to unit, missing private-key in relation data")
            return

        self.charm.workload.write(
            content=self.charm.cluster.private_key, path=f"{self.charm.workload.paths.conf_path}/server.key"
        )

    def set_ca(self) -> None:
        """Sets the unit ca."""
        if not self.charm.cluster.ca:
            logger.error("Can't set CA to unit, missing CA in relation data")
            return

        self.charm.workload.write(content=self.charm.cluster.ca, path=f"{self.charm.workload.paths.conf_path}/ca.pem")

    def set_certificate(self) -> None:
        """Sets the unit certificate."""
        if not self.charm.cluster.certificate:
            logger.error("Can't set certificate to unit, missing certificate in relation data")
            return

        self.charm.workload.write(
            content=self.charm.cluster.certificate, path=f"{self.charm.workload.paths.conf_path}/server.pem"
        )

    def set_truststore(self) -> None:
        """Adds CA to JKS truststore."""
        command = f"charmed-kafka.keytool -import -v -alias ca -file ca.pem -keystore truststore.jks -storepass {self.charm.cluster.truststore_password} -noprompt"
        try:
            self.charm.workload.exec(command=command.split(), working_dir=self.charm.workload.paths.conf_path)
            self.charm.workload.set_snap_ownership(path=f"{self.charm.workload.paths.conf_path}/truststore.jks")
            self.charm.workload.set_snap_mode_bits(path=f"{self.charm.workload.paths.conf_path}/truststore.jks")
        except subprocess.CalledProcessError as e:
            # in case this reruns and fails
            if "already exists" in e.output:
                return
            logger.error(e.output)
            raise e

    def set_keystore(self) -> None:
        """Creates and adds unit cert and private-key to the keystore."""
        command = f"openssl pkcs12 -export -in server.pem -inkey server.key -passin pass:{self.charm.cluster.keystore_password} -certfile server.pem -out keystore.p12 -password pass:{self.charm.cluster.keystore_password}"
        try:
            self.charm.workload.exec(command=command.split(), working_dir=self.charm.workload.paths.conf_path)
            self.charm.workload.set_snap_ownership(path=f"{self.charm.workload.paths.conf_path}/keystore.p12")
            self.charm.workload.set_snap_mode_bits(path=f"{self.charm.workload.paths.conf_path}/keystore.p12")
        except subprocess.CalledProcessError as e:
            logger.error(e.output)
            raise e

    def import_cert(self, alias: str, filename: str) -> None:
        """Add a certificate to the truststore."""
        command = f"charmed-kafka.keytool -import -v -alias {alias} -file {filename} -keystore truststore.jks -storepass {self.charm.cluster.truststore_password} -noprompt"
        try:
            self.charm.workload.exec(command=command.split(), working_dir=self.charm.workload.paths.conf_path)
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
            command = f"charmed-kafka.keytool -delete -v -alias {alias} -keystore truststore.jks -storepass {self.charm.cluster.truststore_password} -noprompt"
            self.charm.workload.exec(
                command=command.split(), working_dir=self.charm.workload.paths.conf_path
            )
            self.charm.workload.exec(
                ["rm", "-f", f"{alias}.pem"], working_dir=self.charm.workload.paths.conf_path
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
            self.charm.workload.exec(
                command=["rm", "-rf", "*.pem", "*.key", "*.p12", "*.jks"],
                working_dir=self.charm.workload.paths.conf_path,
            )
        except subprocess.CalledProcessError as e:
            logger.error(e.output)
            raise e
