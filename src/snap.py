#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""KafkaSnap class and methods."""

import logging
import subprocess
from typing import List

from charms.operator_libs_linux.v0 import apt
from charms.operator_libs_linux.v1 import snap
from tenacity import retry
from tenacity.retry import retry_if_not_result
from tenacity.stop import stop_after_attempt
from tenacity.wait import wait_fixed

from literals import SNAP_NAME

logger = logging.getLogger(__name__)


class KafkaSnap:
    """Wrapper for performing common operations specific to the Kafka Snap."""

    SNAP_NAME = "charmed-kafka"
    COMPONENT = "kafka"
    SNAP_SERVICE = "daemon"

    conf_path = f"/var/snap/{SNAP_NAME}/current/etc/{COMPONENT}"
    logs_path = f"/var/snap/{SNAP_NAME}/common/var/log/{COMPONENT}"
    data_path = f"/var/snap/{SNAP_NAME}/common/var/lib/{COMPONENT}"
    binaries_path = f"/snap/{SNAP_NAME}/current/opt/{COMPONENT}"

    def __init__(self) -> None:
        self.kafka = snap.SnapCache()[SNAP_NAME]

    def install(self) -> bool:
        """Loads the Kafka snap from LP.

        Returns:
            True if successfully installed. False otherwise.
        """
        try:
            apt.update()
            apt.add_package(["snapd", "openjdk-17-jre-headless"])
            cache = snap.SnapCache()
            kafka = cache[SNAP_NAME]

            if not kafka.present:
                kafka.ensure(snap.SnapState.Latest, channel="3/edge")

            self.kafka = kafka
            self.kafka.connect(plug="removable-media")

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
            self.kafka.start(services=[self.SNAP_SERVICE])
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
            self.kafka.stop(services=[self.SNAP_SERVICE])
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
            self.kafka.restart(services=[self.SNAP_SERVICE])
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
        subprocess.run(f"snap disable {self.SNAP_SERVICE}", shell=True)
        subprocess.run(f"snap enable {self.SNAP_SERVICE}", shell=True)

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
            return bool(self.kafka.services[self.SNAP_SERVICE]["active"])
        except KeyError:
            return False

    @staticmethod
    def run_bin_command(bin_keyword: str, bin_args: List[str], opts: List[str] = []) -> str:
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
        command = f"{opts_string} {SNAP_NAME}.{bin_keyword} {args_string}"

        logger.info(f"{command=}")

        try:
            output = subprocess.check_output(
                command, stderr=subprocess.PIPE, universal_newlines=True, shell=True
            )
            logger.debug(f"{output=}")
            return output
        except subprocess.CalledProcessError as e:
            logger.debug(f"cmd failed - cmd={e.cmd}, stdout={e.stdout}, stderr={e.stderr}")
            raise e
