#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""KafkaSnap class and methods

`KafkaSnap` provides a collection of common functions for managing the Kafka Snap and
running bin commands common to both the Kafka and ZooKeeper charms.

The [Kafka Snap](https://snapcraft.io/kafka) tracks the upstream binaries released by
The Apache Software Foundation that comes with [Apache Kafka](https://github.com/apache/kafka).
Currently the snap channel is hard-coded to `rock/edge`.

Exposed methods includes snap installation, starting/restarting the snap service, and running
bin commands exposed in the snap services

Example usage for `KafkaSnap`:

```python

class KafkaCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.snap =  KafkaSnap()

        self.framework.observe(getattr(self.on, "start"), self._on_start)

    def _on_start(self, event):
        self.snap.install()
        self.snap.start_snap_service(snap_service="kafka")
```
"""
import logging
import subprocess
from typing import List

from charms.operator_libs_linux.v0 import apt
from charms.operator_libs_linux.v1 import snap

logger = logging.getLogger(__name__)

# The unique Charmhub library identifier, never change it
LIBID = "db3c8438a0fc435895a2f6a1cccf03a2"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 4


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
            apt.add_package("snapd")
            cache = snap.SnapCache()
            kafka = cache["kafka"]

            if not kafka.present:
                kafka.ensure(snap.SnapState.Latest, channel="rock/edge")

            self.kafka = kafka
            return True
        except (snap.SnapError, apt.PackageNotFoundError) as e:
            logger.error(str(e))
            return False

    def start_snap_service(self, snap_service: str) -> bool:
        """Starts snap service process.

        Args:
            snap_service: The desired service to run on the unit
                `kafka` or `zookeeper`

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
                `kafka` or `zookeeper`

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
        opts_string = " ".join(opts)
        command = f"KAFKA_OPTS={opts_string} kafka.{bin_keyword} {args_string}"

        try:
            output = subprocess.check_output(
                command, stderr=subprocess.PIPE, universal_newlines=True, shell=True
            )
            logger.debug(f"{output=}")
            return output
        except subprocess.CalledProcessError as e:
            logger.debug(f"cmd failed - cmd={e.cmd}, stdout={e.stdout}, stderr={e.stderr}")
            raise e
