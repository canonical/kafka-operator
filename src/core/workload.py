#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Supporting objects for Kafka charm state."""

import secrets
import string
from abc import ABC, abstractmethod

from literals import PATHS


class KafkaPaths:
    """Object to store common paths for Kafka."""

    def __init__(self):
        self.conf_path = PATHS["CONF"]
        self.data_path = PATHS["DATA"]
        self.binaries_path = PATHS["BIN"]
        self.logs_path = PATHS["LOGS"]

    @property
    def server_properties(self):
        """The main server.properties filepath.

        Contains all the main configuration for the service.
        """
        return f"{self.conf_path}/server.properties"

    @property
    def client_properties(self):
        """The main client.properties filepath.

        Contains all the client configuration for the service.
        """
        return f"{self.conf_path}/client.properties"

    @property
    def zk_jaas(self):
        """The zookeeper-jaas.cfg filepath.

        Contains internal+external user credentials used in SASL auth.
        """
        return f"{self.conf_path}/zookeeper-jaas.cfg"

    @property
    def keystore(self):
        """The Java Keystore containing service private-key and signed certificates."""
        return f"{self.conf_path}/keystore.p12"

    @property
    def truststore(self):
        """The Java Truststore containing trusted CAs + certificates."""
        return f"{self.conf_path}/truststore.jks"

    @property
    def log4j_properties(self):
        """The Log4j properties filepath.

        Contains the Log4j configuration options of the service.
        """
        return f"{self.conf_path}/log4j.properties"

    @property
    def jmx_prometheus_javaagent(self):
        """The JMX exporter JAR filepath.

        Used for scraping and exposing mBeans of a JMX target.
        """
        return f"{self.binaries_path}/libs/jmx_prometheus_javaagent.jar"

    @property
    def jmx_prometheus_config(self):
        """The configuration for the JMX exporter."""
        return f"{self.conf_path}/jmx_prometheus.yaml"

    @property
    def cruise_control_properties(self):
        """The cruisecontrol.properties filepath."""
        return f"{self.conf_path}/cruisecontrol.properties"

    @property
    def capacity_jbod_json(self):
        """The JBOD capacity JSON."""
        return f"{self.conf_path}/capacityJBOD.json"


class WorkloadBase(ABC):
    """Base interface for common workload operations."""

    paths = KafkaPaths()

    @abstractmethod
    def start(self, service: str = "") -> None:
        """Starts the workload service.

        Args:
            service: the service to start
        """
        ...

    @abstractmethod
    def stop(self, service: str = "") -> None:
        """Stops the workload service.

        Args:
            service: the service to stop
        """
        ...

    @abstractmethod
    def restart(self, service: str = "") -> None:
        """Restarts the workload service.

        Args:
            service: the service to restart
        """
        ...

    @abstractmethod
    def read(self, path: str) -> list[str]:
        """Reads a file from the workload.

        Args:
            path: the full filepath to read from

        Returns:
            List of string lines from the specified path
        """
        ...

    @abstractmethod
    def write(self, content: str, path: str, mode: str = "w") -> None:
        """Writes content to a workload file.

        Args:
            content: string of content to write
            path: the full filepath to write to
            mode: the write mode. Usually "w" for write, or "a" for append. Default "w"
        """
        ...

    @abstractmethod
    def exec(
        self, command: str, env: dict[str, str] | None = None, working_dir: str | None = None
    ) -> str:
        """Runs a command on the workload substrate."""
        ...

    @abstractmethod
    def active(self) -> bool:
        """Checks that the workload is active."""
        ...

    @abstractmethod
    def run_bin_command(self, bin_keyword: str, bin_args: list[str], opts: list[str] = []) -> str:
        """Runs kafka bin command with desired args.

        Args:
            bin_keyword: the kafka shell script to run
                e.g `configs`, `topics` etc
            bin_args: the shell command args
            opts: any additional opts args strings

        Returns:
            String of kafka bin command output
        """
        ...

    @staticmethod
    def generate_password() -> str:
        """Creates randomized string for use as app passwords.

        Returns:
            String of 32 randomized letter+digit characters
        """
        return "".join([secrets.choice(string.ascii_letters + string.digits) for _ in range(32)])
