#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Balancer."""

import json
from typing import TYPE_CHECKING

from literals import STORAGE

if TYPE_CHECKING:
    from charm import KafkaCharm
    from events.broker import BrokerOperator


class BalancerManager:
    """Manager for handling Balancer."""

    def __init__(self, dependent: "BrokerOperator") -> None:
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
