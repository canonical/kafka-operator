#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling CruiseControl."""

import json

from ops.model import Storage

from core.cluster import ClusterState
from core.workload import WorkloadBase


class CruiseControlManager:
    """Manager for handling CruiseControl."""

    def __init__(
        self,
        state: ClusterState,
        workload: WorkloadBase,
        unit_storages: list[Storage],
    ):
        self.state = state
        self.workload = workload
        self.unit_storages = unit_storages

    def _get_storage_size(self, path: str) -> int:
        """Gets the total storage volume of a mounted filepath, in KB."""
        return int(self.workload.exec(f"df --output=size {path} | sed 1d"))

    @property
    def storages(self) -> str:
        """A string of JSON containing key storage-path, value storage size for all unit storages."""
        return json.dumps(
            {
                storage.location: self._get_storage_size(
                    path=storage.location.absolute().as_posix()
                )
                for storage in self.unit_storages
            }
        )
