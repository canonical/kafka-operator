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
import glob
from dataclasses import dataclass
from subprocess import STDOUT, CalledProcessError, check_output

logger = logging.getLogger(__name__)

# The unique Charmhub library identifier, never change it
LIBID = "17a6cd4d80104d15b10f9c2420ab3266"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 2


SYSCTL_DIRECTORY = "/etc/sysctl.d"
SYSCTL_FILENAME = f"{SYSCTL_DIRECTORY}/95-juju-sysctl.conf"
SYSCTL_HEADER = f"""# This config file was produced by sysctl lib v{LIBAPI}.{LIBPATCH}
#
# This file represents the output of the sysctl lib, which can combine multiple
# configurations into a single file like this with the help of validation rules. Such
# rules are used to automatically resolve simple conflicts between two or more charms
# on one host and is defined as a comment after the configuration option, see example
# below.
#
# Description of validation rules to check if values are valid.
#   - "range(a,b)" - all numbers between 'a' (included) and 'b' (excluded)
#   - "a|b|c" - choices 'a', 'b' and 'c'
#   - "*" - any value
#   - "" or no comment - only current value, same as "<current value>"
#   - "disable" - This value will be ignored in any validation and should only be used by
#                 the charm operator manually or via a charm to override any system
#                 configuration.
# Examples:
# # any value in [10, 50] is valid value
# vm.swappiness=10  # range(10,51)
#
# # 60 and 80 are valid values
# vm.dirty_ratio = 80  # 60|80
#
# # any value is valid
# vm.dirty_background_ratio = 3  # *
#
# # only value 1 is valid value
# net.ipv6.conf.all.use_tempaddr = 1
#
# # validation is disabled
# net.ipv6.conf.default.use_tempaddr = 0  # disable
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
    """Raised when there's an error in the validation process."""


@dataclass()
class ConfigOption:
    """Definition of a config option.
    
    NOTE: this class can be extended to handle the rule tied to each option.
    """
    name: str
    value: int

    @property
    def string_format(self) -> str:
        return f"{self.name}={self.value}"


class SysctlConfig:
    """Represents the state of the config that a charm wants to enforce."""

    def __init__(self, config_params: dict[str, dict], app_name: str) -> None:
        self.config_params = config_params
        self.app_name = app_name

    @property
    def config_params(self) -> list[ConfigOption]:
        """Config options passed to the lib."""
        return self._config_params

    @config_params.setter
    def config_params(self, value: dict):
        result = []
        for k, v in value.items():
            result += [ConfigOption(k, v["value"])]
        self._config_params = result

    @property
    def charm_filepath(self) -> str:
        """Name for resulting charm config file."""
        return f"{SYSCTL_DIRECTORY}/90-juju-{self.app_name}"

    @property
    def charm_config_exists(self) -> bool:
        """Return whether the charm config file exists."""
        return os.path.exists(self.charm_filepath)

    @property
    def merged_config_exists(self) -> bool:
        """Return whether a merged config file exists."""
        return os.path.exists(SYSCTL_FILENAME)

    @property
    def merged_config(self) -> list[ConfigOption] | None:
        """Return applied internal config."""
        if not self.merged_config_exists:
            return None

        with open(SYSCTL_FILENAME, "r") as f:
            return [ConfigOption(param.strip(), int(value.strip()))
                    for line in f.read().splitlines()
                    if line and not line.startswith('#')
                    for param, value in [line.split('=')]]

    def update(self) -> None:
        """Update sysctl config options."""
        if self.charm_config_exists:
            return
        self._create_charm_file()

        if not self.validate():
            raise ValidationError()

        snapshot = self._create_snapshot()
        logger.debug(f"Created snapshot for keys: {snapshot}")
        try:
            self._apply()
        except SysctlPermissionError:
            self._restore_snapshot(snapshot)
            raise
        except ValidationError:
            raise
        self._merge()

    def validate(self) -> bool:
        """Validate the desired config params against merged ones."""
        return True

    def _create_charm_file(self) -> None:
        """Write the charm file."""
        charm_params = [f"{param.string_format}\n" for param in self.config_params]
        with open(self.charm_filepath, "w") as f:
            f.writelines(charm_params)

    def _merge(self) -> None:
        """Create the merged sysctl file."""
        # get all files that start by 90-juju-
        charm_files = [f for f in glob.glob(f"{SYSCTL_DIRECTORY}/90-juju-*")]
        data = [SYSCTL_HEADER]
        for path in charm_files:
            with open(path, "r") as f:
                data += f.readlines()
        with open(SYSCTL_FILENAME, "w") as f:
            f.writelines(data)

    def _apply(self) -> list[str] | None:
        """Apply values to machine.

        Returns:
            none or the list of keys that failed to apply.
        """
        cmd = ["-p", self.charm_filepath]
        result = self._sysctl(cmd)
        expr = re.compile(r'^sysctl: permission denied on key \"([a-z_\.]+)\", ignoring$')
        failed_values = [expr.match(line) for line in result if expr.match(line)]

        if failed_values:
            msg = f"Unable to set params: {[f.group(1) for f in failed_values]}"
            logger.error(msg)
            raise SysctlPermissionError(msg)

    def _create_snapshot(self) -> list[ConfigOption]:
        """Create a snaphot of config options that are going to be set."""
        keys = [param.name for param in self.config_params]
        return [ConfigOption(key, int(self._sysctl([key, "-n"])[0])) for key in keys]

    def _restore_snapshot(self, snapshot: list[ConfigOption]) -> None:
        """Restore a snapshot to the machine."""
        for param in snapshot:
            self._sysctl([param.string_format])

    def _sysctl(self, cmd: list[str]) -> list[str]:
        """Execute a sysctl command."""
        cmd = ["sysctl"] + cmd
        logger.debug(f"Executing sysctl command: {cmd}")
        try:
            return check_output(cmd, stderr=STDOUT, universal_newlines=True).splitlines()
        except CalledProcessError as e:
            raise SysctlError(f"Error executing '{cmd}': {e.output}")
