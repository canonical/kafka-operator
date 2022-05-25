# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""## Overview

`kafka_libs.py` provides a collection of common functions for managing snap installation and
config parsing common to both the Kafka and ZooKeeper charms

"""

import logging
from typing import Dict

from charms.operator_libs_linux.v0 import apt
from charms.operator_libs_linux.v1 import snap

logger = logging.getLogger(__name__)

# The unique Charmhub library identifier, never change it
LIBID = "73d0f23286dd469596d358905406dcab"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1


def install_kafka_snap():
    """Loads the Kafka snap from LP

    Raises:
        SnapError: Raised when there's an error installing or removing a snap
        PackageNotFoundError: Raised when a requested package is not known to the system
    """

    apt.update()
    apt.add_package("snapd")

    cache = snap.SnapCache()
    kafka = cache["kafka"]

    if not kafka.present:
        kafka.ensure(snap.SnapState.Latest, channel="rock/edge")


def get_config(path: str) -> Dict[str, str]:
    """Grabs active config lines from *.properties."""
    with open(path, "r") as f:
        config = f.readlines()

    config_map = {}

    for conf in config:
        if conf[0] != "#" and not conf.isspace():
            logger.debug(conf.strip())
            config_map[conf.split("=")[0]] = conf.split("=")[1].strip()

    return config_map


def merge_config(default: str, override: str) -> str:
    """Merges snap config overrides with default upstream *.properties."""
    default_config = get_config(path=default)

    try:
        override_config = get_config(path=override)
        final_config = {**default_config, **override_config}
    except FileNotFoundError:
        logging.info("no manual config found")
        final_config = default_config

    msg = ""
    for k, v in final_config.items():
        msg = f"{msg}{k}={v}\n"
    return msg

