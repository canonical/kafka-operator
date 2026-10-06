#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""KafkaSnap class and methods."""

import logging
import re

from charmlibs import pathops
from ops import Container, pebble
from ops.pebble import ExecError
from typing_extensions import override

from core.workload import CharmedKafkaPaths, WorkloadBase
from literals import BALANCER, BROKER, CHARM_KEY, GROUP, JMX_CC_PORT, JMX_EXPORTER_PORT, USER_NAME

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

    @property
    @override
    def container_can_connect(self) -> bool:
        return self.container.can_connect()

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
        self, command: list[str], env: dict[str, str] | None = None, working_dir: str | None = None
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
            logger.debug(e)
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

    @override
    def get_version(self) -> str:
        if not self.active:
            return ""
        try:
            version = re.split(r"[\s\-]", self.run_bin_command("topics", ["--version"]))[0]
        except:  # noqa: E722
            version = ""
        return version

    @property
    @override
    def layer(self) -> pebble.Layer:
        """Returns a Pebble configuration layer for Kafka."""
        extra_opts = [
            f"-javaagent:{self.paths.jmx_prometheus_javaagent}={JMX_EXPORTER_PORT}:{self.paths.jmx_prometheus_config}",
            f"-Djava.security.auth.login.config={self.paths.zk_jaas}",
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
                        "JAVA_HOME": "/usr/lib/jvm/java-18-openjdk-amd64",
                        "LOG_DIR": self.paths.logs_path,
                    },
                }
            },
        }
        return pebble.Layer(layer_config)


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

    @override
    def get_version(self) -> str:
        raise NotImplementedError

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
                        "JAVA_HOME": "/usr/lib/jvm/java-18-openjdk-amd64",
                        "LOG_DIR": self.paths.logs_path,
                    },
                }
            },
        }
        return pebble.Layer(layer_config)
