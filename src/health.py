#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka machine health."""

import json
import logging
import subprocess
from statistics import mean
from typing import TYPE_CHECKING

from ops.framework import Object

from literals import JVM_MEM_MAX_GB, JVM_MEM_MIN_GB

if TYPE_CHECKING:
    from charm import KafkaCharm
    from events.broker import BrokerOperator

logger = logging.getLogger(__name__)


class KafkaHealth(Object):
    """Manager for handling Kafka machine health."""

    def __init__(self, dependent: "BrokerOperator") -> None:
        super().__init__(dependent, "kafka_health")
        self.dependent = dependent
        self.charm: "KafkaCharm" = dependent.charm

        if self.charm.substrate == "k8s":
            raise Exception("Health object cannot be instantiated on K8s charms.")

    @property
    def _service_pid(self) -> int:
        """Gets most recent Kafka service pid from the snap logs."""
        return self.dependent.workload.get_service_pid()

    def _get_current_memory_maps(self) -> int:
        """Gets the current number of memory maps for the Kafka process."""
        return int(
            self.dependent.workload.exec(
                ["bash", "-c", f"cat /proc/{self._service_pid}/maps | wc -l"]
            )
        )

    def _get_current_max_files(self) -> int:
        """Gets the current file descriptor limit for the Kafka process."""
        return int(
            self.dependent.workload.exec(
                [
                    "bash",
                    "-c",
                    rf"cat /proc/{self._service_pid}/limits | grep files | awk '{{print $5}}'",
                ]
            )
        )

    def _get_max_memory_maps(self) -> int:
        """Gets the current memory map limit for the machine."""
        return int(self.dependent.workload.exec(["sysctl", "-n", "vm.max_map_count"]))

    def _get_vm_swappiness(self) -> int:
        """Gets the current vm.swappiness configured for the machine."""
        return int(self.dependent.workload.exec(["sysctl", "-n", "vm.swappiness"]))

    def _get_partitions_size(self) -> tuple[int, int]:
        """Gets the number of partitions and their average size from the log dirs."""
        log_dirs_command = [
            "--describe",
            f"--bootstrap-server {self.charm.state.bootstrap_server_internal}",
            f"--command-config {self.dependent.workload.paths.client_properties}",
        ]
        try:
            log_dirs = self.dependent.workload.run_bin_command(
                bin_keyword="log-dirs",
                bin_args=log_dirs_command,
                opts=[self.dependent.config_manager.tools_log4j_opts],
            )
        except subprocess.CalledProcessError:
            return (0, 0)

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
            logger.warning(
                f"number of Kafka memory maps {current_maps} is approaching limit of {max_maps} - increase /etc/sysctl.conf vm.max_map_count limit and restart machine"
            )
            return False

        return True

    def _check_file_descriptors(self) -> bool:
        """Checks that the number of used file descriptors is not approaching threshold."""
        if not self.dependent.config_manager.client_listeners:
            return True

        total_partitions, average_partition_size = self._get_partitions_size()
        segment_size = self.charm.config.log_segment_bytes

        minimum_fd_limit = total_partitions * (average_partition_size / segment_size)
        current_max_files = self._get_current_max_files()

        # eyeballing warning if 80% used, can be changed
        if current_max_files * 0.8 <= minimum_fd_limit:
            logger.warning(
                f"number of required Kafka file descriptors {minimum_fd_limit} is approaching limit of {current_max_files} - increase /etc/security/limits.d/root.conf limit and restart machine"
            )
            return False

        return True

    def _check_vm_swappiness(self) -> bool:
        """Checks that vm.swappiness is configured correctly on the machine."""
        vm_swappiness = self._get_vm_swappiness()

        if vm_swappiness > 1:
            logger.error(
                f"machine vm.swappiness setting of {vm_swappiness} is higher than 1 - set /etc/syscl.conf vm.swappiness=1 and restart machine"
            )
            return False

        return True

    def _check_total_memory(self) -> bool:
        """Checks that the total available memory is sufficient for desired profile."""
        if not (meminfo := self.dependent.workload.read(path="/proc/meminfo")):
            return False

        total_memory_gb = int(meminfo[0].split()[1]) / 1000000
        target_memory_gb = (
            JVM_MEM_MIN_GB if self.charm.config.profile == "testing" else JVM_MEM_MAX_GB
        )

        # TODO: with memory barely above JVM heap, there will be no room for OS page cache, degrading perf
        # need to figure out a better way of ensuring sufficiently beefy machines
        if target_memory_gb >= total_memory_gb:
            logger.error(
                f"Insufficient total memory '{round(total_memory_gb, 2)}' for desired performance profile '{self.charm.config.profile}' - redeploy with greater than {target_memory_gb}GB available memory"
            )
            return False

        return True

    def machine_configured(self) -> bool:
        """Checks machine configuration for healthy settings.

        Returns:
            True if settings safely configured. Otherwise False
        """
        if not all(
            [
                self._check_total_memory(),
                self._check_memory_maps(),
                self._check_file_descriptors(),
                self._check_vm_swappiness(),
            ]
        ):
            return False

        return True
