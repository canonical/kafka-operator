from dataclasses import dataclass
from enum import Enum


@dataclass
class User:
    """Class representing the user running the Pebble workload services."""

    name: str
    group: str


class IOMode(str, Enum):
    """Class representing the modes to open file resources."""

    READ = "r"
    WRITE = "w"
