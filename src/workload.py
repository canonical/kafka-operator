#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""KafkaSnap class and methods."""

import logging
import os
import subprocess

from charms.operator_libs_linux.v0 import apt
from charms.operator_libs_linux.v1 import snap
from tenacity import retry
from tenacity.retry import retry_if_not_result
from tenacity.stop import stop_after_attempt
from tenacity.wait import wait_fixed
from typing_extensions import override

from core.workload import WorkloadBase
from literals import CHARMED_KAFKA_SNAP_REVISION, GROUP, SNAP_NAME, USER

logger = logging.getLogger(__name__)


class KafkaWorkload(WorkloadBase):
    """Wrapper for performing common operations specific to the Kafka Snap."""

    # FIXME: Paths and constants integrated into WorkloadBase?
    SNAP_NAME = "charmed-kafka"
    SNAP_SERVICE = "daemon"
    LOG_SLOT = "logs"

    def __init__(self) -> None:
        self.kafka = snap.SnapCache()[SNAP_NAME]

    @override
    def start(self, service: str = "") -> None:
        service = service or self.SNAP_SERVICE
        try:
            self.kafka.start(services=[service])
        except snap.SnapError as e:
            logger.exception(str(e))

    @override
    def stop(self, service: str = "") -> None:
        service = service or self.SNAP_SERVICE
        try:
            self.kafka.stop(services=[service])
        except snap.SnapError as e:
            logger.exception(str(e))

    @override
    def restart(self, service: str = "") -> None:
        service = service or self.SNAP_SERVICE
        try:
            self.kafka.restart(services=[service])
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

        self.exec(f"chown -R {USER}:{GROUP} {path}")

    @override
    def exec(
        self, command: str, env: dict[str, str] | None = None, working_dir: str | None = None
    ) -> str:
        try:
            output = subprocess.check_output(
                command,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                shell=True,
                cwd=working_dir,
                env=env,
            )
            logger.debug(f"{output=}")
            return output
        except subprocess.CalledProcessError as e:
            logger.debug(f"cmd failed - cmd={e.cmd}, stdout={e.stdout}, stderr={e.stderr}")
            raise e

    @retry(
        wait=wait_fixed(1),
        stop=stop_after_attempt(5),
        retry_error_callback=lambda state: state.outcome.result(),  # type: ignore
        retry=retry_if_not_result(lambda result: True if result else False),
    )
    @override
    def active(self) -> bool:
        try:
            return bool(self.kafka.services[self.SNAP_SERVICE]["active"])
        except KeyError:
            return False

    @override
    def run_bin_command(self, bin_keyword: str, bin_args: list[str], opts: list[str] = []) -> str:
        opts_str = " ".join(opts)
        bin_str = " ".join(bin_args)
        command = f"{opts_str} {SNAP_NAME}.{bin_keyword} {bin_str}"
        return self.exec(command)

    def install(self) -> bool:
        """Loads the Kafka snap from LP.

        Returns:
            True if successfully installed. False otherwise.
        """
        try:
            apt.update()
            apt.add_package(["snapd"])

            self.kafka.ensure(snap.SnapState.Present, revision=CHARMED_KAFKA_SNAP_REVISION)
            self.kafka.connect(plug="removable-media")
            self.kafka.hold()

            return True
        except (snap.SnapError, apt.PackageNotFoundError) as e:
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

                if f"{self.SNAP_NAME}.{self.SNAP_SERVICE}" in content:
                    logger.debug(
                        f"Found Snap service {self.SNAP_SERVICE} for {self.SNAP_NAME} with PID {pid}"
                    )
                    return int(pid)

        raise snap.SnapError(f"Snap {self.SNAP_NAME} pid not found")
