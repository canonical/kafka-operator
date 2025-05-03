#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""KafkaSnap class and methods."""

import logging
import os
import subprocess
from typing import Mapping

from charms.operator_libs_linux.v1 import snap
from ops import Container, pebble
from tenacity import RetryError, Retrying, stop_after_attempt, wait_fixed
from typing_extensions import override

from core.workload import CharmedKafkaPaths, WorkloadBase
from literals import (
    BALANCER,
    BROKER,
    CHARMED_KAFKA_SNAP_REVISION,
    GROUP,
    SNAP_NAME,
    USER,
)

logger = logging.getLogger(__name__)


class Workload(WorkloadBase):
    """Wrapper for performing common operations specific to the Kafka Snap."""

    # FIXME: Paths and constants integrated into WorkloadBase?
    SNAP_NAME = "charmed-kafka"
    LOG_SLOTS = ["kafka-logs", "cc-logs"]

    paths: CharmedKafkaPaths
    service: str

    def __init__(self, container: Container | None = None) -> None:
        self.container = container
        self.kafka = snap.SnapCache()[SNAP_NAME]
        self.attempted_start = False

    @property
    @override
    def container_can_connect(self) -> bool:
        return True  # Always True on VM

    @override
    def start(self) -> None:
        try:
            self.kafka.start(services=[self.service])
            # during current hook execution, store state that we've tried to start
            # state is persisted across deferred events
            # as such, can check active without slowing down init with workload.active retries
            self.attempted_start = True
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
        if not os.path.exists(path):
            return []
        else:
            with open(path) as f:
                content = f.read().split("\n")

        return content

    @override
    def write(self, content: str, path: str, mode: str = "w") -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, mode) as f:
            f.write(content)

        self.exec(["chown", "-R", f"{USER}:{GROUP}", f"{path}"])

    @override
    def exec(
        self,
        command: list[str] | str,
        env: Mapping[str, str] | None = None,
        working_dir: str | None = None,
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
            logger.error(f"cmd failed - cmd={e.cmd}, stdout={e.stdout}, stderr={e.stderr}")
            raise e

    @override
    def active(self) -> bool:
        try:
            # only attempt retries during 'start' hook executions
            # when ZK sends relation data, it may be restarting or not have registered the broker yet
            # so retries only valuable during 'start'
            if not self.attempted_start:
                return bool(self.kafka.services[self.service]["active"])

            for attempt in Retrying(stop=stop_after_attempt(5), wait=wait_fixed(3)):
                with attempt:
                    return bool(self.kafka.services[self.service]["active"])
        except (KeyError, RetryError):
            return False

        return False

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


class KafkaWorkload(Workload):
    """Broker specific wrapper."""

    def __init__(self, container: Container | None = None) -> None:
        super().__init__(container=container)
        self.paths = CharmedKafkaPaths(BROKER)
        self.service = BROKER.service
        self.container = container

    @property
    @override
    def layer(self) -> pebble.Layer:
        raise NotImplementedError


class BalancerWorkload(Workload):
    """Balancer specific wrapper."""

    def __init__(self, container: Container | None = None) -> None:
        super().__init__(container=container)
        self.paths = CharmedKafkaPaths(BALANCER)
        self.service = BALANCER.service
        self.container = container

    @override
    def get_version(self) -> str:
        raise NotImplementedError

    @property
    @override
    def layer(self) -> pebble.Layer:
        raise NotImplementedError
