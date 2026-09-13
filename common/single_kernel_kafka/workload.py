#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Kafka Workload class and methods."""

import csv
import datetime
import fnmatch
import glob as _glob
import logging
import os
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from io import StringIO
from typing import BinaryIO, Mapping, cast

from charmlibs import pathops, snap
from ops import Container, pebble
from ops.pebble import ExecError, FileType
from tenacity import (
    retry,
    retry_any,
    retry_if_exception,
    retry_if_result,
    stop_after_attempt,
    wait_fixed,
)
from typing_extensions import override

from .core.literals import (
    BALANCER,
    BROKER,
    CHARM_KEY,
    CHARMED_KAFKA_SNAP_REVISION,
    GROUP,
    JMX_CC_PORT,
    JMX_EXPORTER_PORT,
    SECURITY_PROTOCOL_PORTS,
    SNAP_NAME,
    USER_NAME,
    AuthMap,
    ConnectLiterals,
)
from .core.workload import CharmedKafkaPaths, ConnectPaths, DirEntry, WorkloadBase

logger = logging.getLogger(__name__)


class WorkloadMachine(WorkloadBase):
    """Wrapper for performing common operations specific to the Kafka Snap."""

    # FIXME: Paths and constants integrated into WorkloadBase?
    SNAP_NAME = "charmed-kafka"
    # Slots for the kafka related logs
    # See https://github.com/canonical/charmed-kafka-snap for details and check
    # refresh_versions.toml to find out what is the snap revision.
    LOG_SLOTS = ["kafka-logs", "kraft-logs", "cc-logs", "connect-logs"]

    paths: CharmedKafkaPaths
    service: str

    def __init__(self, container: Container | None = None) -> None:
        self.connect_paths = ConnectPaths(substrate="vm")
        self.paths = CharmedKafkaPaths(BROKER)  # subclasses can override this
        self.container = container
        self.kafka = snap.SnapCache()[SNAP_NAME]
        self.root = pathops.LocalPath("/")
        self.substrate = "vm"

    @property
    @override
    def container_can_connect(self) -> bool:
        return True  # Always True on VM

    @override
    def start(self) -> None:
        try:
            self.kafka.start(services=[self.service])
        except snap.SnapError as e:
            logger.exception(str(e))

    @override
    def stop(self) -> None:
        try:
            self.kafka.stop(services=[self.service])
        except snap.SnapError as e:
            logger.exception(str(e))

    @override
    def restart(self) -> None:
        try:
            self.kafka.restart(services=[self.service])
        except snap.SnapError as e:
            logger.exception(str(e))

    @override
    def read(self, path: str) -> list[str]:
        return (
            [] if not (self.root / path).exists() else (self.root / path).read_text().split("\n")
        )

    @override
    def write(self, content: str | BinaryIO, path: str, mode: str = "w") -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, mode) as f:
            f.write(content)

        self.exec(["chown", "-R", f"{USER_NAME}:{GROUP}", f"{path}"])

    @override
    def mkdir(self, path: str) -> None:
        self.exec(["mkdir", path])

    @override
    def rmdir(self, path: str) -> None:
        self.exec(["rm", "-r", path])

    @override
    def remove(self, path: str, glob: bool = False) -> None:
        if not glob:
            self.exec(["rm", path])
            return

        for file in _glob.glob(path):
            self.exec(["rm", "-rf", file])

    @override
    def dir_exists(self, path: str) -> bool:
        return os.path.isdir(path)

    @override
    def ls(self, path: str) -> list[DirEntry]:
        return [DirEntry(name=f.name, is_dir=f.is_dir()) for f in os.scandir(path)]

    @override
    def set_environment(self, env_vars: Iterable[str]) -> None:
        raw_current_env = self.read(self.connect_paths.env)
        current_env = self.map_env(raw_current_env)

        updated_env = current_env | self.map_env(env_vars)
        content = "\n".join([f"{key}={value}" for key, value in updated_env.items()])
        self.write(content=content + "\n", path=self.connect_paths.env)

    @override
    def exec(
        self,
        command: list[str] | str,
        env: Mapping[str, str] | None = None,
        working_dir: str | None = None,
        log_on_error: bool = True,
    ) -> str:
        try:
            output = subprocess.check_output(
                command,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                shell=isinstance(command, str),
                env=env,
                cwd=working_dir,
            )
            logger.debug(f"{output=}")
            return output
        except subprocess.CalledProcessError as e:
            if log_on_error:
                logger.error(f"cmd failed - cmd={e.cmd}, stdout={e.stdout}, stderr={e.stderr}")
            raise e

    @override
    @retry(
        wait=wait_fixed(1),
        stop=stop_after_attempt(5),
        retry=retry_if_result(lambda result: result is False),
        retry_error_callback=lambda _: False,
    )
    def active(self) -> bool:
        try:
            return bool(self.kafka.services[self.service]["active"])
        except KeyError:
            return False

    @override
    def modify_time(self, file: str) -> float:
        path = cast(pathops.LocalPath, self.root / file)

        if not path.exists():
            return 0.0

        return path.stat().st_mtime

    @property
    @override
    def installed(self) -> bool:
        return self.kafka.present

    @property
    @override
    def last_restart(self) -> float:
        raw = self.exec(f"snap changes --abs-time {SNAP_NAME}")

        # convert multiple spaces to tab
        raw = re.sub(r" {2,}", "\t", raw)

        # Format of snap changes output:
        # ID  Status  Spawn  Ready  Summary
        f = StringIO(raw)
        output = list(iter(csv.DictReader(f, delimiter="\t")))

        # Convert datetime strings to pythonic objects
        for item in output:
            item["Spawn"] = datetime.datetime.fromisoformat(item["Spawn"])
            item["Ready"] = datetime.datetime.fromisoformat(item["Ready"])

        # Changes are ordered ASC by time, so reverse the list
        service_changes = [
            item
            for item in output[::-1]
            if item["Status"].lower() == "done"
            and item["Summary"].lower() == "running service command"
        ]

        if not service_changes:
            return 0.0

        return cast(datetime.datetime, service_changes[0]["Ready"]).timestamp()

    def install(self) -> bool:
        """Loads the Kafka snap from LP.

        Returns:
            True if successfully installed. False otherwise.
        """
        try:
            self.kafka.ensure(snap.SnapState.Present, revision=CHARMED_KAFKA_SNAP_REVISION)
            self.kafka.connect(plug="removable-media")
            self.kafka.hold()
            return True
        except snap.SnapError as e:
            logger.error(str(e))
            return False

    def disable_enable(self) -> None:
        """Disables then enables snap service.

        Necessary for snap services to recognise new storage mounts

        Raises:
            subprocess.CalledProcessError if error occurs
        """
        subprocess.run(f"snap disable {self.SNAP_NAME}", shell=True)
        subprocess.run(f"snap enable {self.SNAP_NAME}", shell=True)

    def get_service_pid(self) -> int:
        """Gets pid of a currently active snap service.

        Returns:
            Integer of pid

        Raises:
            SnapError if error occurs or if no pid string found in most recent log
        """
        java_processes = subprocess.check_output(
            "pidof java", stderr=subprocess.PIPE, universal_newlines=True, shell=True
        )
        logger.debug(f"Java processes: {java_processes}")

        for pid in java_processes.split():
            with open(f"/proc/{pid}/cgroup", "r") as fid:
                content = "".join(fid.readlines())

                if f"{self.SNAP_NAME}.{self.service}" in content:
                    logger.debug(
                        f"Found Snap service {self.service} for {self.SNAP_NAME} with PID {pid}"
                    )
                    return int(pid)

        raise snap.SnapError(f"Snap {self.SNAP_NAME} pid not found")

    @override
    def run_bin_command(
        self, bin_keyword: str, bin_args: list[str], opts: list[str] | None = None
    ) -> str:
        if opts is None:
            opts = []
        opts_str = " ".join(opts)
        bin_str = " ".join(bin_args)
        command = f"{opts_str} {SNAP_NAME}.{bin_keyword} {bin_str}"
        return self.exec(command)


class KafkaWorkloadMachine(WorkloadMachine):
    """Broker specific wrapper."""

    def __init__(self, container: Container | None = None) -> None:
        super().__init__(container=container)
        self.service = BROKER.service
        self.container = container

    @property
    @override
    def layer(self) -> pebble.Layer:
        raise NotImplementedError

    @staticmethod
    def _parse_metric_value(raw: str, metric: str) -> float | None:
        """Parse a metric value from the prometheus export output."""
        val = None
        for line in raw.split("\n"):
            if not line.startswith("#"):
                parts = line.split()
                if metric.lower() in parts[0]:
                    val = float(parts[1].strip())
                    break

        return val

    @retry(
        wait=wait_fixed(4),
        stop=stop_after_attempt(5),
        retry=retry_any(
            retry_if_result(lambda res: res is False), retry_if_exception(lambda _: True)
        ),
        retry_error_callback=lambda _: False,
    )
    def health_check(self, host: str, runs_broker: bool, runs_controller: bool) -> bool:
        """Check overall workload health."""
        auth_map = AuthMap(protocol="SASL_SSL", mechanism="SCRAM-SHA-512")
        if runs_controller:
            assert self.ping(f"{host}:{SECURITY_PROTOCOL_PORTS[auth_map].controller}")

        if not runs_broker:
            return True

        assert self.ping(f"{host}:{SECURITY_PROTOCOL_PORTS[auth_map].internal}")

        raw = self.exec(["curl", f"http://localhost:{JMX_EXPORTER_PORT}"])

        under_min_isr_count = self._parse_metric_value(raw, "UnderMinIsrPartitionCount")
        # replica_imbalance_count = self._parse_metric_value(raw, "PreferredReplicaImbalanceCount")

        return under_min_isr_count == 0.0


class BalancerWorkloadMachine(WorkloadMachine):
    """Balancer specific wrapper."""

    def __init__(self, container: Container | None = None) -> None:
        super().__init__(container=container)
        self.paths = CharmedKafkaPaths(BALANCER)
        self.service = BALANCER.service
        self.container = container

    @property
    @override
    def layer(self) -> pebble.Layer:
        raise NotImplementedError


class ConnectWorkloadMachine(WorkloadMachine):
    """Kafka Connect specific wrapper."""

    def __init__(self, container: Container | None = None) -> None:
        super().__init__(container=container)
        self.service = ConnectLiterals.SERVICE_NAME
        self.container = container

    @property
    @override
    def layer(self) -> pebble.Layer:
        raise NotImplementedError


### K8s Implementation


class WorkloadK8s(WorkloadBase):
    """Wrapper for performing common operations specific to the Kafka container."""

    paths: CharmedKafkaPaths
    service: str

    @dataclass
    class _Version:
        """Compatibility workload version data for K8s."""

        version = "4"
        revision = None

    def __init__(self, container: Container | None) -> None:
        if not container:
            raise AttributeError("Container is required.")

        self.container = container
        self.root = pathops.ContainerPath("/", container=self.container)
        self.substrate = "k8s"
        self.kafka = self._Version()
        self.paths = CharmedKafkaPaths(BROKER)  # subclasses can override this
        self.connect_paths = ConnectPaths(substrate="k8s")

    @override
    def modify_time(self, file: str) -> float:
        path = cast(pathops.ContainerPath, self.root / file)

        if not path.exists() or not (file_info := path._try_get_fileinfo()):
            return 0.0

        return file_info.last_modified.timestamp()

    @property
    @override
    def container_can_connect(self) -> bool:
        return self.container.can_connect()

    @property
    @override
    def installed(self) -> bool:
        return self.container_can_connect

    @property
    @override
    def last_restart(self) -> float:
        raw = self.exec(["pebble", "services", "--abs-time"])

        # convert multiple spaces to tab
        raw = re.sub(r" {2,}", "\t", raw)

        # Format of pebble services output:
        # Service  Startup  Current  Since
        f = StringIO(raw)
        output = list(iter(csv.DictReader(f, delimiter="\t")))

        # Convert datetime strings to pythonic objects
        for item in output:
            try:
                item["Since"] = datetime.datetime.fromisoformat(item["Since"])
            except ValueError:
                item["Since"] = datetime.datetime.min

        # Changes are ordered ASC by time, so reverse the list
        service = [
            item
            for item in output
            if item["Current"].lower() == "active" and item["Service"] == self.service
        ]

        if not service:
            return 0.0

        return cast(datetime.datetime, service[0]["Since"]).timestamp()

    @override
    def start(self) -> None:
        self.container.add_layer(CHARM_KEY, self.layer, combine=True)
        self.container.restart(self.service)

    @override
    def stop(self) -> None:
        self.container.stop(self.service)

    @override
    def restart(self) -> None:
        self.start()

    @override
    def read(self, path: str) -> list[str]:
        return (
            [] if not (self.root / path).exists() else (self.root / path).read_text().split("\n")
        )

    @override
    def write(self, content: str | BinaryIO, path: str, mode: str = "w") -> None:
        self.container.push(path, content, make_dirs=True)

    @override
    def exec(
        self,
        command: list[str],
        env: dict[str, str] | None = None,
        working_dir: str | None = None,
        log_on_error: bool = True,
    ) -> str:
        try:
            process = self.container.exec(
                command=command,
                environment=env,
                working_dir=working_dir,
                combine_stderr=True,
            )
            output, _ = process.wait_output()
            return output
        except ExecError as e:
            if log_on_error:
                logger.error(f"cmd failed - cmd={command}, stdout={e.stdout}, stderr={e.stderr}")
            raise e

    @override
    def active(self) -> bool:
        if not self.container.can_connect():
            return False

        if self.service not in self.container.get_services():
            return False

        return self.container.get_service(self.service).is_running()

    @override
    def run_bin_command(
        self,
        bin_keyword: str,
        bin_args: list[str],
        opts: list[str] = [],
    ) -> str:
        """Runs kafka bin command with desired args.

        Args:
            bin_keyword: the kafka shell script to run
                e.g `configs`, `topics` etc
            bin_args: the shell command args
            opts: any additional environment strings

        Returns:
            String of kafka bin command output
        """
        parsed_opts = {}
        for opt in opts:
            k, v = opt.split("=", maxsplit=1)
            parsed_opts[k] = v.replace("'", "")

        command = f"{self.paths.binaries_path}/bin/kafka-{bin_keyword}.sh {' '.join(bin_args)}"
        return self.exec(command=command.split(), env=parsed_opts or None)

    @override
    def mkdir(self, path: str) -> None:
        try:
            self.exec(["mkdir", path])
        except pebble.ExecError as e:
            if "File exists" in str(e):
                return
            raise e

    @override
    def rmdir(self, path: str) -> None:
        self.exec(["rm", "-r", path])

    @override
    def remove(self, path: str, glob: bool = False) -> None:
        if not glob:
            self.exec(["rm", path])
            return

        dirname = os.path.dirname(path)
        for file in self.container.list_files(dirname):
            if fnmatch.fnmatch(file.path, path):
                self.exec(["rm", "-rf", file.path])

    @override
    def dir_exists(self, path: str) -> bool:
        """Checks whether a directory exists at provided path on the workload."""
        if not self.container_can_connect:
            return False

        return self.container.isdir(path)

    @override
    def ls(self, path: str) -> list[DirEntry]:
        """Returns a directory listing of provided path on the workload."""
        if not self.container_can_connect:
            return []

        return [
            DirEntry(name=f.name, is_dir=(f.type == FileType.DIRECTORY))
            for f in self.container.list_files(path)
        ]

    @override
    def set_environment(self, env_vars: Iterable[str]) -> None:
        raw_current_env = self.read(self.connect_paths.env)
        current_env = self.map_env(raw_current_env)

        updated_env = current_env | self.map_env(env_vars)
        content = "\n".join([f"{key}={value}" for key, value in updated_env.items()])
        self.write(content=content + "\n", path=self.connect_paths.env)

    # ------- Kafka vm specific -------

    def install(self) -> None:
        """Loads the Kafka snap from LP.

        Returns:
            True if successfully installed. False otherwise.
        """
        raise NotImplementedError

    def get_service_pid(self) -> int:
        """Gets pid of a currently active snap service.

        Returns:
            Integer of pid

        Raises:
            SnapError if error occurs or if no pid string found in most recent log
        """
        raise NotImplementedError


class KafkaWorkloadK8s(WorkloadK8s):
    """Broker specific wrapper."""

    def __init__(self, container: Container | None) -> None:
        super().__init__(container)

        self.paths = CharmedKafkaPaths(BROKER)
        self.service = BROKER.service

    @property
    @override
    def layer(self) -> pebble.Layer:
        """Returns a Pebble configuration layer for Kafka."""
        extra_opts = [
            f"-javaagent:{self.paths.jmx_prometheus_javaagent}={JMX_EXPORTER_PORT}:{self.paths.jmx_prometheus_config}",
        ]
        command = (
            f"{self.paths.binaries_path}/bin/kafka-server-start.sh {self.paths.server_properties}"
        )

        layer_config: pebble.LayerDict = {
            "summary": "kafka layer",
            "description": "Pebble config layer for kafka",
            "services": {
                BROKER.service: {
                    "override": "merge",
                    "summary": "kafka",
                    "command": command,
                    "startup": "enabled",
                    "user": str(USER_NAME),
                    "group": GROUP,
                    "environment": {
                        "KAFKA_OPTS": " ".join(extra_opts),
                        # FIXME https://github.com/canonical/kafka-k8s-operator/issues/80
                        "JAVA_HOME": "/usr/lib/jvm/java-21-openjdk-amd64",
                        "LOG_DIR": self.paths.logs_path,
                    },
                }
            },
        }
        return pebble.Layer(layer_config)

    @staticmethod
    def _parse_metric_value(raw: str, metric: str) -> float | None:
        """Parse a metric value from the prometheus export output."""
        val = None
        for line in raw.split("\n"):
            if not line.startswith("#"):
                parts = line.split()
                if metric.lower() in parts[0]:
                    val = float(parts[1].strip())
                    break

        return val

    @retry(
        wait=wait_fixed(4),
        stop=stop_after_attempt(5),
        retry=retry_any(
            retry_if_result(lambda res: res is False), retry_if_exception(lambda _: True)
        ),
        retry_error_callback=lambda _: False,
    )
    def health_check(self, host: str, runs_broker: bool, runs_controller: bool) -> bool:
        """Check overall workload health."""
        auth_map = AuthMap(protocol="SASL_SSL", mechanism="SCRAM-SHA-512")
        if runs_controller:
            assert self.ping(f"{host}:{SECURITY_PROTOCOL_PORTS[auth_map].controller}")

        if not runs_broker:
            return True

        assert self.ping(f"{host}:{SECURITY_PROTOCOL_PORTS[auth_map].internal}")

        raw = self.exec(["curl", f"http://localhost:{JMX_EXPORTER_PORT}"])

        under_min_isr_count = self._parse_metric_value(raw, "UnderMinIsrPartitionCount")
        # replica_imbalance_count = self._parse_metric_value(raw, "PreferredReplicaImbalanceCount")

        return under_min_isr_count == 0.0


class BalancerWorkloadK8s(WorkloadK8s):
    """Balancer specific wrapper."""

    def __init__(self, container: Container | None) -> None:
        super().__init__(container)
        self.paths = CharmedKafkaPaths(BALANCER)
        self.service = BALANCER.service

    @override
    def run_bin_command(
        self,
        bin_keyword: str,
        bin_args: list[str],
        opts: list[str] = [],
    ) -> str:
        """Runs kafka bin command with desired args.

        Args:
            bin_keyword: the kafka shell script to run
                e.g `configs`, `topics` etc
            bin_args: the shell command args
            opts: any additional environment strings

        Returns:
            String of kafka bin command output
        """
        parsed_opts = {}
        for opt in opts:
            k, v = opt.split("=", maxsplit=1)
            parsed_opts[k] = v.replace("'", "")

        command = f"{BROKER.paths['BIN']}/bin/kafka-{bin_keyword}.sh {' '.join(bin_args)}"
        return self.exec(command=command.split(), env=parsed_opts or None)

    @property
    @override
    def layer(self) -> pebble.Layer:
        """Returns a Pebble configuration layer for CruiseControl."""
        extra_opts = [
            f"-javaagent:{CharmedKafkaPaths(BROKER).jmx_prometheus_javaagent}={JMX_CC_PORT}:{self.paths.jmx_cc_config}",
            f"-Djava.security.auth.login.config={self.paths.balancer_jaas}",
        ]
        command = f"{self.paths.binaries_path}/bin/kafka-cruise-control-start.sh {self.paths.cruise_control_properties}"

        layer_config: pebble.LayerDict = {
            "summary": "kafka layer",
            "description": "Pebble config layer for kafka",
            "services": {
                BALANCER.service: {
                    "override": "replace",
                    "summary": "balancer",
                    "command": command,
                    "startup": "enabled",
                    "user": str(USER_NAME),
                    "group": GROUP,
                    "environment": {
                        "KAFKA_OPTS": " ".join(extra_opts),
                        # FIXME https://github.com/canonical/kafka-k8s-operator/issues/80
                        "JAVA_HOME": "/usr/lib/jvm/java-21-openjdk-amd64",
                        "LOG_DIR": self.paths.logs_path,
                    },
                }
            },
        }
        return pebble.Layer(layer_config)


class ConnectWorkloadK8s(WorkloadK8s):
    """Kafka Connect specific wrapper."""

    def __init__(self, container: Container) -> None:
        super().__init__(container=container)
        self.service = ConnectLiterals.SERVICE_NAME
        self.container = container

    @property
    @override
    def container_can_connect(self) -> bool:
        return self.container.can_connect()

    @property
    @override
    def layer(self) -> pebble.Layer:
        """Returns a Pebble configuration layer for Kafka Connect."""
        extra_opts = [
            f"-javaagent:{self.paths.jmx_prometheus_javaagent}={JMX_EXPORTER_PORT}:{self.connect_paths.jmx_prometheus_config}",
            f"-Djava.security.auth.login.config={self.connect_paths.jaas}",
        ]
        command = f"/opt/kafka/bin/connect-distributed.sh {self.connect_paths.worker_properties}"

        layer_config: pebble.LayerDict = {
            "summary": "Kafka Connect Layer",
            "description": "Pebble config layer for Apache Kafka Connect distributed worker",
            "services": {
                self.service: {
                    "override": "merge",
                    "summary": "Kafka Connect Worker",
                    "command": command,
                    "startup": "enabled",
                    "user": USER_NAME,
                    "group": GROUP,
                    "environment": {
                        "KAFKA_OPTS": " ".join(extra_opts),
                        "JAVA_HOME": "/usr/lib/jvm/java-21-openjdk-amd64",
                        "LOG_DIR": self.connect_paths.logs_dir,
                    },
                }
            },
        }
        return pebble.Layer(layer_config)


KafkaWorkload = KafkaWorkloadMachine | KafkaWorkloadK8s
BalancerWorkload = BalancerWorkloadMachine | BalancerWorkloadK8s
