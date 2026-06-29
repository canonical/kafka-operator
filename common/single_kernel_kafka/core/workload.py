#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Supporting objects for Kafka charm state."""

import logging
import re
import secrets
import socket
import string
from abc import ABC, abstractmethod
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
from typing import BinaryIO

from charmlibs import pathops
from ops.pebble import Layer

from ..core.literals import (
    BALANCER,
    BROKER,
    SNAP_NAME,
    Role,
    Substrates,
    TLSScope,
)

logger = logging.getLogger(__name__)


@dataclass
class DirEntry:
    """Object to represent an entry in directory listing."""

    name: str
    is_dir: bool


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


class ConnectPaths:
    """Object to store common paths for Kafka Connect worker."""

    def __init__(self, substrate: Substrates):

        if substrate == "vm":
            self._config_dir = f"/var/snap/{SNAP_NAME}/current/etc/connect"
            self._plugins_path = f"/var/snap/{SNAP_NAME}/common/var/lib/connect/plugins/"
            self._logs_dir = f"/var/snap/{SNAP_NAME}/common/var/log/connect"
        else:
            self._config_dir = "/etc/connect"
            self._plugins_path = "/var/lib/connect/plugins/"
            self._logs_dir = "/var/logs/connect/"

    @property
    def config_dir(self) -> str:
        """Path to Kafka Connect config directory."""
        return self._config_dir

    @property
    def snap_dir(self) -> str:
        """Path to Kafka & Kafka connect snap's base dir."""
        return f"/snap/{SNAP_NAME}/current/opt/kafka"

    @property
    def logs_dir(self) -> str:
        """Path to logs dir."""
        return self._logs_dir

    @property
    def env(self) -> str:
        """Path to environment file."""
        return "/etc/environment"

    @property
    def plugins(self) -> str:
        """Path to plugins folder or storage."""
        return self._plugins_path

    @property
    def worker_properties(self) -> str:
        """Path to distributed connect worker properties file."""
        return f"{self.config_dir}/connect-distributed.properties"

    @property
    def jaas(self) -> str:
        """Path to authentication JAAS config file."""
        return f"{self.config_dir}/jaas.cfg"

    @property
    def keystore(self) -> str:
        """Path to Java Keystore containing service private-key and signed certificates."""
        return f"{self.config_dir}/connect-keystore.p12"

    @property
    def truststore(self):
        """Path to Java Truststore containing trusted CAs + certificates."""
        return f"{self.config_dir}/connect-truststore.jks"

    @property
    def truststore_password(self) -> str:
        """Path to truststore password file."""
        return f"{self.config_dir}/truststore.password"

    @property
    def passwords(self) -> str:
        """Path to passwords file store when using PropertyFileLoginModule."""
        return f"{self.config_dir}/connect.password"

    @property
    def jmx_prometheus_javaagent(self) -> str:
        """Path to JMX Prometheus exporter java agent."""
        return f"{self.snap_dir}/libs/jmx_prometheus_javaagent.jar"

    @property
    def jmx_prometheus_config(self) -> str:
        """Path to JMX Prometheus exporter YAML config file."""
        return f"{self.config_dir}/jmx_prometheus.yaml"

    @property
    def log4j_properties(self) -> str:
        """Path to log4j properties file."""
        return f"{self.config_dir}/log4j.properties"


class WorkloadBase(ABC):
    """Base interface for common workload operations."""

    paths: CharmedKafkaPaths
    connect_paths: ConnectPaths
    root: pathops.PathProtocol
    substrate: Substrates

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
    def write(self, content: str | BinaryIO, path: str, mode: str = "w") -> None:
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
        sensitive: bool = False,
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

    @abstractmethod
    def mkdir(self, path: str) -> None:
        """Creates a new directory at the provided path."""
        ...

    @abstractmethod
    def rmdir(self, path: str) -> None:
        """Removes the directory at the provided path."""
        ...

    @abstractmethod
    def remove(self, path: str, glob: bool = False) -> None:
        """Removes the file at the provided path."""
        ...

    @abstractmethod
    def dir_exists(self, path: str) -> bool:
        """Checks whether a directory exists at provided path on the workload."""
        ...

    @abstractmethod
    def ls(self, path: str) -> list[DirEntry]:
        """Returns a directory listing of provided path on the workload."""
        ...

    @abstractmethod
    def set_environment(self, env_vars: Iterable[str]) -> None:
        """Updates the environment variables with provided iterable of key=value `env_vars`."""

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
        if not self.container_can_connect:
            return []

        raw = self.exec(["hostname", "-I"]).strip()

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
    def map_env(env: Iterable[str]) -> dict[str, str]:
        """Parse env variables into a dict."""
        map_env = {}
        for var in env:
            key = "".join(var.split("=", maxsplit=1)[0])
            value = "".join(var.split("=", maxsplit=1)[1:])
            if key:
                # only check for keys, as we can have an empty value for a variable
                map_env[key] = value
        return map_env

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


class KafkaWorkloadBase(WorkloadBase):
    """Broker specific wrapper."""

    @abstractmethod
    def health_check(self, host: str, runs_broker: bool, runs_controller: bool) -> bool:
        """Check overall workload health."""
        ...


class BalancerWorkloadBase(WorkloadBase):
    """Balancer specific wrapper."""
