#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Supporting objects for Kafka charm state."""

from abc import ABC, abstractmethod


class PathsBase(ABC):
    def __init__(self, conf_path: str, logs_path: str, data_path: str, binaries_path: str):
        self.conf_path = conf_path
        self.logs_path = logs_path
        self.data_path = data_path
        self.binaries_path = binaries_path


class WorkloadBase(ABC):
    def __init__(self, paths: PathsBase):
        self.paths = paths

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def restart(self) -> None: ...

    @abstractmethod
    def read(self, path: str) -> list[str]:
        """Load file contents from charm workload.

        Args:
            filepath: the filepath to load data from

        Returns:
            List of file content lines
            None if file does not exist
        """
        ...

    @abstractmethod
    def write(self, content: str, path: str, mode: str = "w") -> None:
        """Ensures destination filepath exists before writing.

        Args:
            content: the content to be written to a file
            path: the full destination filepath
            mode: the write mode. Usually "w" for write, or "a" for append. Default "w"
        """
        ...

    @abstractmethod
    def exec(self, command: list[str], env: str, working_dir: str | None = None) -> str: ...

    @abstractmethod
    def update_environment(self, env: dict[str, str]) -> None: ...
