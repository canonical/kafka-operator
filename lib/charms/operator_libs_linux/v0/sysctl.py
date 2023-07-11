# Copyright 2023 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Handler for the sysctl config
"""

import logging
import os
import re
from pathlib import Path
from subprocess import STDOUT, CalledProcessError, check_output
from typing import Mapping, Dict, Optional

logger = logging.getLogger(__name__)

# The unique Charmhub library identifier, never change it
LIBID = "17a6cd4d80104d15b10f9c2420ab3266"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 2


SYSCTL_DIRECTORY = Path("/etc/sysctl.d")
SYSCTL_FILENAME = Path(f"{SYSCTL_DIRECTORY}/95-juju-sysctl.conf")
SYSCTL_HEADER = f"""# This config file was produced by sysctl lib v{LIBAPI}.{LIBPATCH}
#
# This file represents the output of the sysctl lib, which can combine multiple
# configurations into a single file like.
"""


class Error(Exception):
    """Base class of most errors raised by this library."""

    def __repr__(self):
        """Represent the Error."""
        return "<{}.{} {}>".format(type(self).__module__, type(self).__name__, self.args)

    @property
    def name(self):
        """Return a string representation of the model plus class."""
        return "<{}.{}>".format(type(self).__module__, type(self).__name__)

    @property
    def message(self):
        """Return the message passed as an argument."""
        return self.args[0]


class SysctlError(Error):
    """Raised when there's an error running sysctl command."""


class SysctlPermissionError(Error):
    """Raised when there's an error applying values in sysctl."""


class ValidationError(Error):
    """Exception representing value validation error."""


class SysctlConfig(Mapping[str, int]):
    """Represents the state of the config that a charm wants to enforce."""

    def __init__(self, name: Optional[str] = None) -> None:
        self.name = name

    def __contains__(self, key: str) -> bool:
        """Check if key is in config."""
        return key in self._data

    def __len__(self):
        """Get size of config."""
        return len(self._data)

    def __iter__(self):
        """Iterate over config."""
        return iter(self._data)

    def __getitem__(self, key: str) -> int:
        """Get value for key form config."""
        return self._data[key]

    @property
    def _data(self) -> Dict[str, int]:
        """Return applied internal config."""
        if not self.merged_config_exists:
            return {}

        with open(SYSCTL_FILENAME, "r") as f:
            return {param.strip(): int(value.strip())
                    for line in f.read().splitlines()
                    if line and not line.startswith('#')
                    for param, value in [line.split('=')]}

    @property
    def name(self) -> str:
        """Name used to create the lib file."""
        return self._name

    @name.setter
    def name(self, value: str):
        if value is None:
            self._name, *_ = os.getenv("JUJU_UNIT_NAME", "unknown").split("/")
        else:
            self._name = value

    @property
    def charm_filepath(self) -> Path:
        """Name for resulting charm config file."""
        return Path(f"{SYSCTL_DIRECTORY}/90-juju-{self.name}")

    @property
    def charm_config_exists(self) -> bool:
        """Return whether the charm config file exists."""
        return os.path.exists(self.charm_filepath)

    @property
    def merged_config_exists(self) -> bool:
        """Return whether a merged config file exists."""
        return os.path.exists(SYSCTL_FILENAME)

    def update(self, config: Dict[str, dict]) -> None:
        """Update sysctl config options with a desired set of config params."""
        self._parse_config(config)
        if self.charm_config_exists:
            return

        conflict = self.validate()
        if conflict:
            msg = f"Validation error for keys: {conflict}" 
            raise ValidationError(msg)

        snapshot = self._create_snapshot()
        logger.debug(f"Created snapshot for keys: {snapshot}")
        try:
            self._apply()
        except SysctlPermissionError:
            self._restore_snapshot(snapshot)
            raise
        except SysctlError:
            raise

        self._create_charm_file()
        self._merge()

    def validate(self) -> list[str]:
        """Validate the desired config params against merged ones."""
        common_keys = set(self._data.keys()) & set(self._desired_config.keys())
        confict_keys = []
        for key in common_keys:
            if self._data[key] != self._desired_config[key]:
                msg = f"Values for key '{key}' are different: {self._data[key]} != {self._desired_config[key]}"
                logger.warning(msg)
                confict_keys += key

        return confict_keys

    def _create_charm_file(self) -> None:
        """Write the charm file."""
        charm_params = [f"{key}={value}\n" for key, value in self._desired_config.items()]
        with open(self.charm_filepath, "w") as f:
            f.writelines(charm_params)

    def _merge(self) -> None:
        """Create the merged sysctl file."""
        data = (
            [f"# {self.name}\n"] + [f"{key}={value}\n" for key, value in self._desired_config.items()]
        )
        if not self.merged_config_exists:
            data.insert(0, SYSCTL_HEADER)

        with open(SYSCTL_FILENAME, "a+") as f:
            f.writelines(data)

    def _apply(self) -> None:
        """Apply values to machine."""
        cmd = ["-p", self.charm_filepath]
        result = self._sysctl(cmd)
        expr = re.compile(r'^sysctl: permission denied on key \"([a-z_\.]+)\", ignoring$')
        failed_values = [expr.match(line) for line in result if expr.match(line)]
        logger.debug(f"Failed values: {failed_values}")

        if failed_values:
            msg = f"Unable to set params: {[f.group(1) for f in failed_values]}"
            logger.error(msg)
            raise SysctlPermissionError(msg)

    def _create_snapshot(self) -> Dict[str, int]:
        """Create a snaphot of config options that are going to be set."""
        return {key: int(self._sysctl([key, "-n"])[0]) for key in self._desired_config.keys()}

    def _restore_snapshot(self, snapshot: Dict[str, int]) -> None:
        """Restore a snapshot to the machine."""
        for key, value in snapshot.items():
            self._sysctl([f"{key}={value}"])

    def _sysctl(self, cmd: list[str]) -> list[str]:
        """Execute a sysctl command."""
        cmd = ["sysctl"] + cmd
        logger.debug(f"Executing sysctl command: {cmd}")
        try:
            return check_output(cmd, stderr=STDOUT, universal_newlines=True).splitlines()
        except CalledProcessError as e:
            raise SysctlError(f"Error executing '{cmd}': {e.output}")

    def _parse_config(self, config: Dict[str, dict]) -> None:
        """Parse a config passed to the lib."""
        result = {}
        for k, v in config.items():
            result[k]=v["value"]
        self._desired_config: Dict[str, int] = result
