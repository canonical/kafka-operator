#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Balancer."""

import json
import logging
from typing import TYPE_CHECKING

from literals import BALANCER, BALANCER_TOPICS, STORAGE

if TYPE_CHECKING:
    from charm import KafkaCharm
    from events.balancer import BalancerOperator
    from events.broker import BrokerOperator


logger = logging.getLogger(__name__)


class BalancerManager:
    """Manager for handling Balancer."""

    def __init__(self, dependent: "BrokerOperator | BalancerOperator") -> None:
        self.dependent = dependent
        self.charm: "KafkaCharm" = dependent.charm

    def _get_storage_size(self, path: str) -> int:
        """Gets the total storage volume of a mounted filepath, in KB."""
        return int(self.dependent.workload.exec(f"df --output=size {path} | sed 1d"))

    @property
    def cores(self) -> int:
        """Gets the total number of CPU cores for the machine."""
        return int(self.dependent.workload.exec("nproc --all"))

    @property
    def storages(self) -> str:
        """A string of JSON containing key storage-path, value storage size for all unit storages."""
        return json.dumps(
            {
                str(storage.location): str(
                    self._get_storage_size(path=storage.location.absolute().as_posix())
                )
                for storage in self.charm.model.storages[STORAGE]
            }
        )

    def create_internal_topics(self) -> None:
        """Create Cruise Control topics."""
        # if self.charm.state.runs_broker:
        #     property_file = f'{BROKER.paths["CONF"]}/client.properties'
        #     bootstrap_servers = self.charm.state.internal_bootstrap_server
        # else:
        bootstrap_servers = self.charm.state.balancer.broker_uris
        property_file = f'{BALANCER.paths["CONF"]}/cruisecontrol.properties'

        for topic in BALANCER_TOPICS:
            if topic not in self.dependent.workload.run_bin_command(
                "topics",
                [
                    "--list",
                    "--bootstrap-server",
                    bootstrap_servers,
                    "--command-config",
                    property_file,
                ],
            ):
                self.dependent.workload.run_bin_command(
                    "topics",
                    [
                        "--create",
                        "--topic",
                        topic,
                        "--bootstrap-server",
                        bootstrap_servers,
                        "--command-config",
                        property_file,
                    ],
                )
                logger.info(f"Created topic {topic}")
