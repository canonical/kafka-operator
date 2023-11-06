#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""KafkaSnap class and methods."""

import logging
import re
import subprocess
from typing import List

from tenacity import retry
from tenacity.retry import retry_if_not_result
from tenacity.stop import stop_after_attempt
from tenacity.wait import wait_fixed

from charms.operator_libs_linux.v0 import apt
from charms.operator_libs_linux.v1 import snap

logger = logging.getLogger(__name__)


class SnapService:
    """Wrapper for performing common operations specific to the Kafka Snap."""

    def __init__(self,
                 name: str, component: str, service: str, revision: int,
                 log_slot: str, plugs: List[str]
                 ) -> None:
        self.name = name
        self.component = component
        self.service = service
        self.log_slot = log_slot
        self.plugs = plugs
        self.revision = revision

        self._snap = snap.SnapCache()[self.name]

    def install(self) -> bool:
        """Loads the Kafka snap from LP.

        Returns:
            True if successfully installed. False otherwise.
        """
        try:
            apt.update()
            apt.add_package(["snapd"])

            self._snap.ensure(snap.SnapState.Present, revision=self.revision)

            for plug in self.plugs:
                self._snap.connect(plug=plug)

            self._snap.hold()

            return True
        except (snap.SnapError, apt.PackageNotFoundError) as e:
            logger.error(str(e))
            return False

    def start_snap_service(self) -> bool:
        """Starts snap service process.

        Returns:
            True if service successfully starts. False otherwise.
        """
        try:
            self._snap.start(services=[self.service])
            return True
        except snap.SnapError as e:
            logger.exception(str(e))
            return False

    def stop_snap_service(self) -> bool:
        """Stops snap service process.

        Returns:
            True if service successfully stops. False otherwise.
        """
        try:
            self._snap.stop(services=[self.service])
            return True
        except snap.SnapError as e:
            logger.exception(str(e))
            return False

    def restart_snap_service(self) -> bool:
        """Restarts snap service process.

        Returns:
            True if service successfully restarts. False otherwise.
        """
        try:
            self._snap.restart(services=[self.service])
            return True
        except snap.SnapError as e:
            logger.exception(str(e))
            return False

    def disable_enable(self) -> None:
        """Disables then enables snap service.

        Necessary for snap services to recognise new storage mounts

        Raises:
            subprocess.CalledProcessError if error occurs
        """
        subprocess.run(f"snap disable {self.name}", shell=True)
        subprocess.run(f"snap enable {self.name}", shell=True)

    @retry(
        wait=wait_fixed(1),
        stop=stop_after_attempt(5),
        retry_error_callback=lambda state: state.outcome.result(),  # type: ignore
        retry=retry_if_not_result(lambda result: True if result else False),
    )
    def active(self) -> bool:
        """Checks if service is active.

        Returns:
            True if service is active. Otherwise False

        Raises:
            KeyError if service does not exist
        """
        try:
            return bool(self._snap.services[self.service]["active"])
        except KeyError:
            return False

    def get_service_pid(self) -> int:
        """Gets pid of a currently active snap service.

        Returns:
            Integer of pid

        Raises:
            SnapError if error occurs or if no pid string found in most recent log
        """
        last_log = self._snap.logs(services=[self.service], num_lines=1)
        pid_string = re.search(rf"{self.name}.{self.service}\[([0-9]+)\]", last_log)

        if not pid_string:
            raise snap.SnapError("pid not found in snap logs")

        return int(pid_string[1])

    def run_bin_command(
            self, bin_keyword: str, bin_args: List[str], opts: List[str] = []
    ) -> str:
        """Runs kafka bin command with desired args.

        Args:
            bin_keyword: the kafka shell script to run
                e.g `configs`, `topics` etc
            bin_args: the shell command args
            opts: any additional opts args strings

        Returns:
            String of kafka bin command output

        Raises:
            `subprocess.CalledProcessError`: if the error returned a non-zero exit code
        """
        args_string = " ".join(bin_args)
        opts_string = " ".join(opts)
        command = f"{opts_string} {self.name}.{bin_keyword} {args_string}"
        try:
            output = subprocess.check_output(
                command, stderr=subprocess.PIPE, universal_newlines=True, shell=True
            )
            logger.debug(f"{output=}")
            return output
        except subprocess.CalledProcessError as e:
            logger.debug(f"cmd failed - cmd={e.cmd}, stdout={e.stdout}, stderr={e.stderr}")
            raise e
