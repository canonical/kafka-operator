#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Collection of helper methods for checking active connections between ZK and Kafka."""

import logging
import os
import secrets
import string
from typing import Dict, List, Optional, Set

from charms.zookeeper.v0.client import ZooKeeperManager
from kazoo.exceptions import AuthFailedError, NoNodeError
from ops.model import Unit
from tenacity import retry
from tenacity.retry import retry_if_not_result
from tenacity.stop import stop_after_attempt
from tenacity.wait import wait_fixed

logger = logging.getLogger(__name__)


@retry(
    # retry to give ZK time to update its broker zNodes before failing
    wait=wait_fixed(5),
    stop=stop_after_attempt(6),
    retry_error_callback=(lambda state: state.outcome.result()),
    retry=retry_if_not_result(lambda result: True if result else False),
)
def broker_active(unit: Unit, zookeeper_config: Dict[str, str]) -> bool:
    """Checks ZooKeeper for client connections, checks for specific broker id.

    Args:
        unit: the `Unit` to check connection of
        zookeeper_config: the relation provided by ZooKeeper

    Returns:
        True if broker id is recognised as active by ZooKeeper. Otherwise False.
    """
    broker_id = unit.name.split("/")[1]
    brokers = get_active_brokers(zookeeper_config=zookeeper_config)
    chroot = zookeeper_config.get("chroot", "")
    return f"{chroot}/brokers/ids/{broker_id}" in brokers


def get_active_brokers(zookeeper_config: Dict[str, str]) -> Set[str]:
    """Gets all brokers currently connected to ZooKeeper.

    Args:
        zookeeper_config: the relation data provided by ZooKeeper

    Returns:
        Set of active broker ids
    """
    chroot = zookeeper_config.get("chroot", "")
    hosts = zookeeper_config.get("endpoints", "").split(",")
    username = zookeeper_config.get("username", "")
    password = zookeeper_config.get("password", "")

    zk = ZooKeeperManager(hosts=hosts, username=username, password=password)
    path = f"{chroot}/brokers/ids/"

    try:
        brokers = zk.leader_znodes(path=path)
    # auth might not be ready with ZK after relation yet
    except (NoNodeError, AuthFailedError) as e:
        logger.debug(str(e))
        return set()

    return brokers


def safe_get_file(filepath: str) -> Optional[List[str]]:
    """Load file contents from charm workload.

    Args:
        filepath: the filepath to load data from

    Returns:
        List of file content lines
        None if file does not exist
    """
    if not os.path.exists(filepath):
        return None
    else:
        with open(filepath) as f:
            content = f.read().split("\n")

    return content


def safe_write_to_file(content: str, path: str, mode: str = "w") -> None:
    """Ensures destination filepath exists before writing.

    Args:
        content: the content to be written to a file
        path: the full destination filepath
        mode: the write mode. Usually "w" for write, or "a" for append. Default "w"
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode) as f:
        f.write(content)

    return


def generate_password() -> str:
    """Creates randomized string for use as app passwords.

    Returns:
        String of 32 randomized letter+digit characters
    """
    return "".join([secrets.choice(string.ascii_letters + string.digits) for _ in range(32)])
