# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""## Overview

`kafka_snap.py` provides a collection of common functions for managing snap installation and
config parsing common to both the Kafka and ZooKeeper charms

"""

import logging
from typing import Dict, List

from ops.model import StatusBase
from charms.operator_libs_linux.v0 import apt
from charms.operator_libs_linux.v1 import snap
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus

logger = logging.getLogger(__name__)

# The unique Charmhub library identifier, never change it
LIBID = "73d0f23286dd469596d358905406dcab"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 4


class KafkaSnap:
    def __init__(self) -> None:
        self.default_config_path = "/snap/kafka/current/opt/kafka/config/"
        self.snap_config_path = "/var/snap/kafka/common/"
        self.kafka = snap.SnapCache()["kafka"] 

    def install_kafka_snap(self) -> StatusBase:
        """Loads the Kafka snap from LP, returning a StatusBase for the Charm to set."""

        try:
            apt.update()
            apt.add_package("snapd")
            cache = snap.SnapCache()
            kafka = cache["kafka"]

            if not kafka.present:
                kafka.ensure(snap.SnapState.Latest, channel="rock/edge")

            self.kafka = kafka 
            logger.info("sucessfully installed kafka snap")
            return MaintenanceStatus("sucessfully installed kafka snap")

        except (snap.SnapError, apt.PackageNotFoundError):
            return BlockedStatus("failed to install kakfa snap")

    def get_kafka_apps(self) -> List:
        """Grabs apps from the snap property."""
        apps = self.kafka.apps

        return apps


    def start_snap_service(self, snap_service: str) -> StatusBase:
        """Starts snap service process

        Args:
            snap_service (str): The desired service to run on the unit
                `kafka` or `zookeeper`
        Returns:
            ActiveStatus (StatusBase): If service starts successfully
            BlockedStatus (StatusBase): If service fails to start
        """
        try:
            self.kafka.start(services=[snap_service])
            logger.info(f"successfully started snap service: {snap_service}")
            return ActiveStatus()
        except snap.SnapError as e:
            logger.error(e)
            return BlockedStatus(f"failed starting snap service: {snap_service}")


    @staticmethod
    def get_properties(path: str) -> Dict[str, str]:
        """Grabs active config lines from *.properties."""
        with open(path, "r") as f:
            config = f.readlines()

        config_map = {}

        for conf in config:
            if conf[0] != "#" and not conf.isspace():
                logger.debug(conf.strip())
                config_map[conf.split("=")[0]] = conf.split("=")[1].strip()

        return config_map

    def get_merged_properties(self, property_label: str) -> str:
        """Merges snap config overrides with default upstream *.properties.

        Args:
            property_label (str): The prefix of the desired *.properties file
                e.g `server` or `zookeeper`

        Returns:
           str: The merged default and user config
        """

        default_path = self.default_config_path + f"{property_label}.properties"
        default_config = self.get_properties(path=default_path)

        override_path = self.snap_config_path + f"{property_label}.properties"

        try:
            override_config = self.get_properties(path=override_path)
            final_config = {**default_config, **override_config}
        except FileNotFoundError:
            logging.info("no manual config found")
            final_config = default_config

        return "\n".join([f"{k}={v}" for k,v in final_config.items()]) 
