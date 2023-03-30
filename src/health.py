#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka machine health."""

import json
import logging
import subprocess
from statistics import mean
from typing import TYPE_CHECKING, Tuple

from ops.framework import Object

from literals import Status

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)


class KafkaHealth(Object):
    """Manager for handling Kafka machine health."""

    def __init__(self, charm) -> None:
        super().__init__(charm, "kafka_health")
        self.charm: "KafkaCharm" = charm

    @property
    def _service_pid(self) -> int:
        """Gets most recent Kafka service pid from the snap logs."""
        return self.charm.snap.get_service_pid()

    def _get_current_memory_maps(self) -> int:
        """Gets the current number of memory maps for the Kafka process."""
        return int(
            subprocess.check_output(
                f"cat /proc/{self._service_pid}/maps | wc -l",
                shell=True,
                stderr=subprocess.PIPE,
                universal_newlines=True,
            )
        )

    def _get_current_max_files(self) -> int:
        """Gets the current file descriptor limit for the Kafka process."""
        return int(
            subprocess.check_output(
                rf"cat /proc/{self._service_pid}/limits | grep files | awk '{{print $5}}'",
                shell=True,
                stderr=subprocess.PIPE,
                universal_newlines=True,
            )
        )

    def _get_max_memory_maps(self) -> int:
        """Gets the current memory map limit for the machine."""
        return int(
            subprocess.check_output(
                "sysctl -n vm.max_map_count",
                shell=True,
                stderr=subprocess.PIPE,
                universal_newlines=True,
            )
        )

    def _get_vm_swappiness(self) -> int:
        """Gets the current vm.swappiness configured for the machine."""
        return int(
            subprocess.check_output(
                "sysctl -n vm.swappiness",
                shell=True,
                stderr=subprocess.PIPE,
                universal_newlines=True,
            )
        )

    def _get_partitions_size(self) -> Tuple[int, int]:
        """Gets the number of partitions and their average size from the log dirs."""
        log_dirs_command = [
            "--describe",
            f"--bootstrap-server {','.join(self.charm.kafka_config.bootstrap_server)}",
            f"--command-config {self.charm.kafka_config.client_properties_filepath}",
        ]
        log_dirs = self.charm.snap.run_bin_command(
            bin_keyword="log-dirs", bin_args=log_dirs_command
        )

        dirs = {}
        for line in log_dirs.splitlines():
            try:
                # filters stdout to only relevant lines
                dirs = json.loads(line)
                break
            except json.decoder.JSONDecodeError:
                continue

        if not dirs:
            return (0, 0)

        partitions = []
        sizes = []
        for broker in dirs["brokers"]:
            for log_dir in broker["logDirs"]:
                for partition in log_dir["partitions"]:
                    partitions.append(partition["partition"])
                    sizes.append(int(partition["size"]))

        if not sizes or not partitions:
            return (0, 0)

        average_partition_size = mean(sizes)
        total_partitions = len(partitions)

        return (total_partitions, average_partition_size)

    def _check_memory_maps(self) -> bool:
        """Checks that the number of used memory maps is not approaching threshold."""
        max_maps = self._get_max_memory_maps()
        current_maps = self._get_current_memory_maps()

        # eyeballing warning if 80% used, can be changed
        if max_maps * 0.8 <= current_maps:
            self.charm._set_status(Status.NEAR_MMAP_LIMIT)
            return False

        return True

    def _check_file_descriptors(self) -> bool:
        """Checks that the number of used file descriptors is not approaching threshold."""
        if not self.charm.kafka_config.client_listeners:
            return True

        total_partitions, average_partition_size = self._get_partitions_size()
        segment_size = int(self.charm.config["log_segment_bytes"])

        minimum_fd_limit = total_partitions * (average_partition_size / segment_size)
        current_max_files = self._get_current_max_files()

        # eyeballing warning if 80% used, can be changed
        if current_max_files * 0.8 <= minimum_fd_limit:
            self.charm._set_status(Status.NEAR_FD_LIMIT)
            return False

        return True

    def _check_vm_swappiness(self) -> bool:
        """Checks that vm.swappiness is configured correctly on the machine."""
        vm_swappiness = self._get_vm_swappiness()

        if vm_swappiness > 1:
            self.charm._set_status(Status.TOO_SWAPPY)
            return False

        return True

    def machine_configured(self) -> bool:
        """Checks machine configuration for healthy settings.

        Returns:
            True if settings safely configured. Otherwise False
        """
        if not self._check_memory_maps():
            return False

        if not self._check_file_descriptors():
            return False

        if not self._check_vm_swappiness():
            return False

        return True
