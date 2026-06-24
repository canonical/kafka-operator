#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""KafkaSnap class and methods."""

import csv
import datetime
import logging
import re
from io import StringIO

from charmlibs import pathops
from ops import Container, pebble
from ops.pebble import ExecError
from tenacity import (
    retry,
    retry_any,
    retry_if_exception,
    retry_if_result,
    stop_after_attempt,
    wait_fixed,
)
from typing_extensions import cast, override

from core.workload import CharmedKafkaPaths, WorkloadBase
from literals import (
    BALANCER,
    BROKER,
    CHARM_KEY,
    GROUP,
    JMX_CC_PORT,
    JMX_EXPORTER_PORT,
    SECURITY_PROTOCOL_PORTS,
    USER_NAME,
    AuthMap,
)

logger = logging.getLogger(__name__)


class Workload(WorkloadBase):
    """Wrapper for performing common operations specific to the Kafka container."""

    paths: CharmedKafkaPaths
    service: str

    def __init__(self, container: Container | None) -> None:
        if not container:
            raise AttributeError("Container is required.")

        self.container = container
        self.root = pathops.ContainerPath("/", container=self.container)

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
    def write(self, content: str, path: str) -> None:
        (self.root / path).write_text(content, user=USER_NAME, group=GROUP)

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


class KafkaWorkload(Workload):
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


class BalancerWorkload(Workload):
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
