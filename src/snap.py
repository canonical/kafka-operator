#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""KafkaSnap class and methods."""

import logging
import subprocess
from typing import List

from charms.operator_libs_linux.v0 import apt
from charms.operator_libs_linux.v1 import snap

logger = logging.getLogger(__name__)


SNAP_CONFIG_PATH = "/var/snap/kafka/common/"


class KafkaSnap:
    """Wrapper for performing common operations specific to the Kafka Snap."""

    def __init__(self) -> None:
        self.snap_config_path = SNAP_CONFIG_PATH
        self.kafka = snap.SnapCache()["kafka"]

    def install(self) -> bool:
        """Loads the Kafka snap from LP, returning a StatusBase for the Charm to set.

        Returns:
            True if successfully installed. False otherwise.
        """
        try:
            apt.update()
            apt.add_package(["snapd", "openjdk-17-jre-headless"])
            cache = snap.SnapCache()
            kafka = cache["charmed-kafka"]
            node_exporter = cache["node-exporter"]

            if not kafka.present:
                kafka.ensure(snap.SnapState.Latest, channel="latest/edge")
            if not node_exporter.present:
                node_exporter.ensure(snap.SnapState.Latest, channel="edge")

            self.kafka = kafka
            self.kafka.connect(plug="removable-media")

            node_exporter_plugs = [
                "hardware-observe",
                "network-observe",
                "mount-observe",
                "system-observe",
            ]
            for plug in node_exporter_plugs:
                node_exporter.connect(plug=plug)

            return True
        except (snap.SnapError, apt.PackageNotFoundError) as e:
            logger.error(str(e))
            return False

    def start_snap_service(self, snap_service: str) -> bool:
        """Starts snap service process.

        Args:
            snap_service: The desired service to run on the unit
                `charmed-kafka` or `zookeeper`

        Returns:
            True if service successfully starts. False otherwise.
        """
        try:
            self.kafka.start(services=[snap_service])
            return True
        except snap.SnapError as e:
            logger.exception(str(e))
            return False

    def stop_snap_service(self, snap_service: str) -> bool:
        """Stops snap service process.

        Args:
            snap_service: The desired service to stop on the unit
                `charmed-kafka` or `zookeeper`

        Returns:
            True if service successfully stops. False otherwise.
        """
        try:
            self.kafka.stop(services=[snap_service])
            return True
        except snap.SnapError as e:
            logger.exception(str(e))
            return False

    def restart_snap_service(self, snap_service: str) -> bool:
        """Restarts snap service process.

        Args:
            snap_service: The desired service to run on the unit
                `kafka` or `zookeeper`

        Returns:
            True if service successfully restarts. False otherwise.
        """
        try:
            self.kafka.restart(services=[snap_service])
            return True
        except snap.SnapError as e:
            logger.exception(str(e))
            return False

    def disable_enable(self, snap_service: str) -> None:
        """Disables then enables snap service.

        Necessary for snap services to recognise new storage mounts

        Args:
            snap_service: The desired service to disable+enable

        Raises:
            subprocess.CalledProcessError if error occurs
        """
        subprocess.run(f"snap disable {snap_service}", shell=True)
        subprocess.run(f"snap enable {snap_service}", shell=True)

    @staticmethod
    def run_bin_command(bin_keyword: str, bin_args: List[str], opts: List[str]) -> str:
        """Runs kafka bin command with desired args.

        Args:
            bin_keyword: the kafka shell script to run
                e.g `configs`, `topics` etc
            bin_args: the shell command args
            opts (optional): the desired `KAFKA_OPTS` env var values for the command

        Returns:
            String of kafka bin command output

        Raises:
            `subprocess.CalledProcessError`: if the error returned a non-zero exit code
        """
        args_string = " ".join(bin_args)
        args_string_appended = (
            f"{args_string} --zk-tls-config-file={SNAP_CONFIG_PATH}server.properties"
        )
        opts_string = " ".join(opts)
        command = f"KAFKA_OPTS={opts_string} charmed-kafka.{bin_keyword} {args_string_appended}"

        try:
            output = subprocess.check_output(
                command, stderr=subprocess.PIPE, universal_newlines=True, shell=True
            )
            logger.debug(f"{output=}")
            return output
        except subprocess.CalledProcessError as e:
            logger.debug(f"cmd failed - cmd={e.cmd}, stdout={e.stdout}, stderr={e.stderr}")
            raise e
