#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Supporting objects for Kafka charm state."""

from abc import ABC, abstractmethod


class PathsBase(ABC):
    """Base definition for workload related paths."""

    def __init__(self, conf_path: str, logs_path: str, data_path: str, binaries_path: str):
        self.conf_path = conf_path
        self.logs_path = logs_path
        self.data_path = data_path
        self.binaries_path = binaries_path


class WorkloadBase(ABC):
    """Base interface for common workload operations."""

    @abstractmethod
    def start(self) -> None:
        """Starts the workload service."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Stops the workload service."""
        ...

    @abstractmethod
    def restart(self) -> None:
        """Restarts the workload service."""
        ...

    @abstractmethod
    def read(self, path: str) -> list[str]:
        """Reads a file from the workload.

        Args:
            path: the full filepath to read from

        Returns:
            List of string lines from the specified path
        """
        ...

    @abstractmethod
    def write(self, content: str, path: str, mode: str = "w") -> None:
        """Writes content to a workload file.

        Args:
            content: string of content to write
            path: the full filepath to write to
            mode: the write mode. Usually "w" for write, or "a" for append. Default "w"
        """
        ...

    @abstractmethod
    def exec(self, command: list[str], env: str, working_dir: str | None = None) -> str:
        """Runs a command on the workload substrate."""
        ...

    @abstractmethod
    def active(self) -> bool:
        """Checks that the workload is active."""
        ...
