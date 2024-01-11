#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka TLS configuration."""

import logging
import subprocess

from core.cluster import ClusterState
from vm_workload import KafkaWorkload

logger = logging.getLogger(__name__)


class TLSManager:
    """Manager for building necessary files for Java TLS auth."""

    def __init__(self, state: ClusterState, workload: KafkaWorkload):
        self.state = state
        self.workload = workload

    def generate_alias(self, app_name: str, relation_id: int) -> str:
        """Generate an alias from a relation. Used to identify ca certs."""
        return f"{app_name}-{relation_id}"

    def set_server_key(self) -> None:
        """Sets the unit private-key."""
        if not self.state.broker.private_key:
            logger.error("Can't set private-key to unit, missing private-key in relation data")
            return

        self.workload.write(
            content=self.state.broker.private_key, path=f"{self.workload.paths.conf_path}/server.key"
        )

    def set_ca(self) -> None:
        """Sets the unit ca."""
        if not self.state.broker.ca:
            logger.error("Can't set CA to unit, missing CA in relation data")
            return

        self.workload.write(content=self.state.broker.ca, path=f"{self.workload.paths.conf_path}/ca.pem")

    def set_certificate(self) -> None:
        """Sets the unit certificate."""
        if not self.state.broker.certificate:
            logger.error("Can't set certificate to unit, missing certificate in relation data")
            return

        self.workload.write(
            content=self.state.broker.certificate, path=f"{self.workload.paths.conf_path}/server.pem"
        )

    def set_truststore(self) -> None:
        """Adds CA to JKS truststore."""
        command = f"charmed-kafka.keytool -import -v -alias ca -file ca.pem -keystore truststore.jks -storepass {self.state.broker.truststore_password} -noprompt"
        try:
            self.workload.exec(command=command, working_dir=self.workload.paths.conf_path)
            self.workload.set_snap_ownership(path=f"{self.workload.paths.conf_path}/truststore.jks")
            self.workload.set_snap_mode_bits(path=f"{self.workload.paths.conf_path}/truststore.jks")
        except subprocess.CalledProcessError as e:
            # in case this reruns and fails
            if "already exists" in e.output:
                return
            logger.error(e.output)
            raise e

    def set_keystore(self) -> None:
        """Creates and adds unit cert and private-key to the keystore."""
        command = f"openssl pkcs12 -export -in server.pem -inkey server.key -passin pass:{self.state.broker.keystore_password} -certfile server.pem -out keystore.p12 -password pass:{self.state.broker.keystore_password}"
        try:
            self.workload.exec(command=command, working_dir=self.workload.paths.conf_path)
            self.workload.set_snap_ownership(path=f"{self.workload.paths.conf_path}/keystore.p12")
            self.workload.set_snap_mode_bits(path=f"{self.workload.paths.conf_path}/keystore.p12")
        except subprocess.CalledProcessError as e:
            logger.error(e.output)
            raise e

    def import_cert(self, alias: str, filename: str) -> None:
        """Add a certificate to the truststore."""
        command = f"charmed-kafka.keytool -import -v -alias {alias} -file {filename} -keystore truststore.jks -storepass {self.state.broker.truststore_password} -noprompt"
        try:
            self.workload.exec(command=command, working_dir=self.workload.paths.conf_path)
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
            command = f"charmed-kafka.keytool -delete -v -alias {alias} -keystore truststore.jks -storepass {self.state.broker.truststore_password} -noprompt"
            self.workload.exec(
                command=command, working_dir=self.workload.paths.conf_path
            )
            self.workload.exec(
                f"rm -f {alias}.pem", working_dir=self.workload.paths.conf_path
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
                command="rm -rf *.pem *.key *.p12 *.jks",
                working_dir=self.workload.paths.conf_path,
            )
        except subprocess.CalledProcessError as e:
            logger.error(e.output)
            raise e
