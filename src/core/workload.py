#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Supporting objects for Kafka charm state."""

import re
import secrets
import socket
import string
from abc import ABC, abstractmethod
from contextlib import closing

from charmlibs import pathops
from ops.pebble import Layer

from literals import BALANCER, BROKER, Role, TLSScope


class CharmedKafkaPaths:
    """Object to store common paths for Kafka."""

    def __init__(self, role: Role):

        self.conf_path = role.paths["CONF"]
        self.data_path = role.paths["DATA"]
        self.binaries_path = role.paths["BIN"]
        self.logs_path = role.paths["LOGS"]

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
    def kraft_client_properties(self):
        """The main kraft-client.properties filepath.

        Contains all the client configuration for the KRaft Quorum AdminClient.
        """
        return f"{self.conf_path}/kraft-client.properties"

    @property
    def balancer_jaas(self):
        """The cruise_control_jaas.conf filepath."""
        return f"{self.conf_path}/cruise_control_jaas.conf"

    @property
    def keystore(self):
        """The Java Keystore containing service private-key and signed certificates for clients."""
        return f"{self.conf_path}/{TLSScope.CLIENT.value}-keystore.p12"

    @property
    def truststore(self):
        """The Java Truststore containing trusted CAs + certificates for clients."""
        return f"{self.conf_path}/{TLSScope.CLIENT.value}-truststore.jks"

    @property
    def peer_keystore(self):
        """The Java Keystore containing service private-key and signed certificates for internal peer communications."""
        return f"{self.conf_path}/{TLSScope.PEER.value}-keystore.p12"

    @property
    def peer_truststore(self):
        """The Java Truststore containing trusted CAs + certificates for internal peer communications."""
        return f"{self.conf_path}/{TLSScope.PEER.value}-truststore.jks"

    @property
    def log4j_properties(self):
        """The Log4j properties filepath.

        Contains the Log4j configuration options of the service.
        """
        return f"{self.conf_path}/log4j.properties"

    @property
    def tools_log4j_properties(self):
        """The tooling Log4j properties filepath.

        Contains the Log4j configuration options primarily for the bin commands.
        """
        return f"{self.conf_path}/tools-log4j.properties"

    @property
    def jmx_prometheus_javaagent(self):
        """The JMX exporter JAR filepath.

        Used for scraping and exposing mBeans of a JMX target.
        """
        return f"{self.binaries_path}/libs/jmx_prometheus_javaagent.jar"

    @property
    def jmx_prometheus_config(self):
        """The configuration for the Kafka JMX exporter."""
        return f"{BROKER.paths['CONF']}/jmx_prometheus.yaml"

    @property
    def jmx_cc_config(self):
        """The configuration for the CruiseControl JMX exporter."""
        return f"{BALANCER.paths['CONF']}/jmx_cruise_control.yaml"

    @property
    def cruise_control_properties(self):
        """The cruisecontrol.properties filepath."""
        return f"{self.conf_path}/cruisecontrol.properties"

    @property
    def capacity_jbod_json(self):
        """The JBOD capacity JSON."""
        return f"{self.conf_path}/capacityJBOD.json"

    @property
    def cruise_control_auth(self):
        """The credentials file."""
        return f"{self.conf_path}/cruisecontrol.credentials"


class WorkloadBase(ABC):
    """Base interface for common workload operations."""

    paths: CharmedKafkaPaths
    root: pathops.PathProtocol

    @abstractmethod
    def start(self) -> None:
        """Starts the workload service."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Stops the workload service."""
        ...

    @abstractmethod
    def restart(self) -> None:
        """Restarts the workload service."""
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
        self,
        command: list[str] | str,
        env: dict[str, str] | None = None,
        working_dir: str | None = None,
        log_on_error: bool = True,
    ) -> str:
        """Runs a command on the workload substrate."""
        ...

    @abstractmethod
    def active(self) -> bool:
        """Checks that the workload is active."""
        ...

    @abstractmethod
    def modify_time(self, file: str) -> float:
        """Returns the last modify time of a file on the workload in UNIX timestamp format."""
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

    @property
    @abstractmethod
    def installed(self) -> bool:
        """Checks whether the workload service is installed."""
        ...

    @property
    @abstractmethod
    def layer(self) -> Layer:
        """Gets the Pebble Layer definition for the current workload."""
        ...

    @property
    @abstractmethod
    def container_can_connect(self) -> bool:
        """Flag to check if workload container can connect."""
        ...

    @property
    @abstractmethod
    def last_restart(self) -> float:
        """Returns a UNIX timestamp of last time the service was restarted."""
        ...

    @property
    def ips(self) -> list[str]:
        """Return a list of current IPs associated with the workload, using `hostname -I`."""
        raw = self.exec("hostname -I").strip()

        if not raw:
            return []

        return re.findall(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}", raw)

    @staticmethod
    def generate_password() -> str:
        """Creates randomized string for use as app passwords.

        Returns:
            String of 32 randomized letter+digit characters
        """
        return "".join([secrets.choice(string.ascii_letters + string.digits) for _ in range(32)])

    @staticmethod
    def ping(bootstrap_nodes: str) -> bool:
        """Check if any socket in `bootstrap_nodes` is available or not.

        Args:
            bootstrap_nodes (str): A string representation of bootstrap nodes, in the format: host1:port1,host2:port2,...

        Returns:
            bool: True if any socket is open.
        """
        for host_port in bootstrap_nodes.split(","):
            if ":" not in host_port:
                continue

            host, port = host_port.split(":")
            with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
                if sock.connect_ex((host, int(port))) == 0:
                    return True

        return False
