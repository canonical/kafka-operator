#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""KafkaSnap class and methods

`KafkaSnap` provides a collection of common functions for managing the Kafka Snap and
config management common to both the Kafka and ZooKeeper charms.

The [Kafka Snap](https://snapcraft.io/kafka) tracks the upstream binaries released by
The Apache Software Foundation that comes with [Apache Kafka](https://github.com/apache/kafka).
Currently the snap channel is hard-coded to `rock/edge`.

Exposed methods includes snap installation, starting/restarting the snap service, writing properties and JAAS files
to the machines, setting KAFKA_OPTS env-vars to be loaded at runtime.

Example usage for `KafkaSnap`:

```python

class KafkaCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.snap =  KafkaSnap()

        self.framework.observe(getattr(self.on, "start"), self._on_start)

    def _on_start(self, event):
        self.snap.install()
        self.snap.write_properties(
            properties=self.config["server-properties"],
            property_label="server"
        )
        self.snap.start_snap_service(snap_service="kafka")
```
"""
import logging
import os
import subprocess
from typing import Dict, List

from charms.operator_libs_linux.v0 import apt
from charms.operator_libs_linux.v1 import snap

logger = logging.getLogger(__name__)

# The unique Charmhub library identifier, never change it
LIBID = "db3c8438a0fc435895a2f6a1cccf03a2"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 2


SNAP_CONFIG_PATH = "/var/snap/kafka/common/"


class ConfigError(Exception):
    """Required field is missing from the config."""

    pass


def safe_write_to_file(content: str, path: str, mode: str = "w") -> None:
    """Ensures destination filepath exists before writing.

    args:
        content: The content to be written to a file
        path: The full destination filepath
        mode: The write mode. Usually "w" for write, or "a" for append. Default "w"
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode) as f:
        f.write(content)

    return


class KafkaSnap:
    """Wrapper for performing common operations specific to the Kafka Snap."""

    def __init__(self) -> None:
        self.snap_config_path = SNAP_CONFIG_PATH
        self.kafka = snap.SnapCache()["kafka"]

    def install(self) -> bool:
        """Loads the Kafka snap from LP, returning a StatusBase for the Charm to set.

        If fails with expected errors, it will block the KafkaSnap instance from executing
        additional non-idempotent methods.

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

    def write_properties(self, properties: str, property_label: str, mode: str = "w") -> None:
        """Writes to the expected config file location for the Kafka Snap.

        Args:
            properties: A multiline string containing the properties to be set
            property_label: The file prefix for the config file
                `server` for Kafka, `zookeeper` or `zookeeper-dynamic` for ZooKeeper
            mode: The write mode. Usually "w" for write, or "a" for append. Default "w"
        """

        path = f"{SNAP_CONFIG_PATH}/{property_label}.properties"
        safe_write_to_file(content=properties, path=path, mode=mode)

    def write_zookeeper_myid(self, myid: int, property_label: str = "zookeeper") -> None:
        """Checks the *.properties file for dataDir, and writes ZooKeeper id to <data-dir>/myid.

        Args:
            myid: The desired ZooKeeper server id
                Expected to be (unit id + 1) to index from 1
            property_label: The file prefix for the config file. Default "zookeeper"

        Raises:
            ConfigError: If the dataDir property is not set in the charm config
        """
        properties = self.get_properties(property_label=property_label)
        try:
            myid_path = f"{properties['dataDir']}/myid"
        except KeyError as e:
            logger.error(str(e))
            raise ConfigError("dataDir is not set in the config")

        safe_write_to_file(content=str(myid), path=myid_path, mode="w")

    def get_properties(self, property_label: str) -> Dict[str, str]:
        """Grabs active config lines from *.properties.

        Returns:
            A mapping of config properties and their values

        Raises:
            ConfigError: If the properties file cannot be found in the unit
        """
        path = f"{SNAP_CONFIG_PATH}/{property_label}.properties"
        config_map = {}

        try:
            with open(path, "r") as f:
                config = f.readlines()
        except FileNotFoundError as e:
            logger.error(str(e))
            raise ConfigError(f"missing properties file: {path}")

        for conf in config:
            if conf[0] != "#" and not conf.isspace():
                config_map[str(conf.split("=")[0])] = str(conf.split("=")[1].strip())

        return config_map

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
            logger.exception(e)
            logger.debug(f"cmd failed - cmd={e.cmd}, stdout={e.stdout}, stderr={e.stderr}")
            raise e
