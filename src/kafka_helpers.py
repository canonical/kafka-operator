from charms.operator_libs_linux.v1 import snap
from charms.operator_libs_linux.v0 import apt
from typing import Dict
import logging

logger = logging.getLogger(__name__)

def install_packages():
    apt.update()
    apt.add_package("snapd")

    cache = snap.SnapCache()
    kafka = cache["kafka"]

    if not kafka.present:
        kafka.ensure(snap.SnapState.Latest, channel="rock/edge")

def get_config(path: str) -> Dict[str, str]:
    """Grabs active config lines from *.properties"""

    with open(path, "r") as f:
        config = f.readlines()

    config_map = {}

    for conf in config:
        if conf[0] != "#" and not conf.isspace():
            logger.debug(conf)
            config_map[conf.split("=")[0]] = conf.split("=")[1]

    return config_map


def merge_config(default: str, override: str) -> str:
    """Merges snap config overrides with default upstream *.properties"""

    default_config = get_config(path=default)
    
    try:
        override_config = get_config(path=override)
        for k, v in override_config.items():
            if k in default_config:
                default_config[k] = v
    except FileNotFoundError:
        logging.info("no manual config found")

    msg = ""
    for k, v in default_config.items():
        msg = f"{msg}{k}={v}\n"

    return msg
