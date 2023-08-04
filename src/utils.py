#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Collection of helper methods for checking active connections between ZK and Kafka."""

import base64
import logging
import os
import re
import secrets
import shutil
import string
from typing import Dict, List, Optional, Set

from charms.zookeeper.v0.client import QuorumLeaderNotFoundError, ZooKeeperManager
from kazoo.exceptions import AuthFailedError, NoNodeError
from ops.model import Unit
from tenacity import retry
from tenacity.retry import retry_if_not_result
from tenacity.stop import stop_after_attempt
from tenacity.wait import wait_fixed

logger = logging.getLogger(__name__)


@retry(
    # retry to give ZK time to update its broker zNodes before failing
    wait=wait_fixed(6),
    stop=stop_after_attempt(10),
    retry_error_callback=(lambda state: state.outcome.result()),  # type: ignore
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
    except (NoNodeError, AuthFailedError, QuorumLeaderNotFoundError) as e:
        logger.debug(str(e))
        return set()

    return brokers


def get_zookeeper_version(zookeeper_config: Dict[str, str]) -> str:
    """Get running zookeeper version.

    Args:
        zookeeper_config: the relation provided by ZooKeeper

    Returns:
        zookeeper version
    """
    hosts = zookeeper_config.get("endpoints", "").split(",")
    username = zookeeper_config.get("username", "")
    password = zookeeper_config.get("password", "")

    zk = ZooKeeperManager(hosts=hosts, username=username, password=password)

    return zk.get_version()


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

    set_snap_ownership(path=path)


def set_snap_ownership(path: str) -> None:
    """Sets a filepath `snap_daemon` ownership."""
    shutil.chown(path, user="snap_daemon", group="root")

    for root, dirs, files in os.walk(path):
        for fp in dirs + files:
            shutil.chown(os.path.join(root, fp), user="snap_daemon", group="root")


def set_snap_mode_bits(path: str) -> None:
    """Sets filepath mode bits."""
    os.chmod(path, 0o770)

    for root, dirs, files in os.walk(path):
        for fp in dirs + files:
            os.chmod(os.path.join(root, fp), 0o770)


def generate_password() -> str:
    """Creates randomized string for use as app passwords.

    Returns:
        String of 32 randomized letter+digit characters
    """
    return "".join([secrets.choice(string.ascii_letters + string.digits) for _ in range(32)])


def parse_tls_file(raw_content: str) -> str:
    """Parse TLS files from both plain text or base64 format."""
    if re.match(r"(-+(BEGIN|END) [A-Z ]+-+)", raw_content):
        return raw_content
    return base64.b64decode(raw_content).decode("utf-8")


def map_env(env: list[str]) -> dict[str, str]:
    """Builds environment map for arbitrary env-var strings.

    Returns:
        Dict of env-var and value
    """
    map_env = {}
    for var in env:
        key = "".join(var.split("=", maxsplit=1)[0])
        value = "".join(var.split("=", maxsplit=1)[1:])
        if key:
            # only check for keys, as we can have an empty value for a variable
            map_env[key] = value

    return map_env


def get_env() -> dict[str, str]:
    """Builds map of current basic environment for all processes.

    Returns:
        Dict of env-var and value
    """
    raw_env = safe_get_file("/etc/environment") or []
    return map_env(env=raw_env)


def update_env(env: dict[str, str]) -> None:
    """Updates /etc/environment file."""
    updated_env = get_env() | env
    content = "\n".join([f"{key}={value}" for key, value in updated_env.items()])
    safe_write_to_file(content=content, path="/etc/environment", mode="w")
