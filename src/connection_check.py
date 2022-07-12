#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Collection of helper methods for checking active connections between ZK and Kafka."""

import logging
from typing import Dict

from charms.zookeeper.v0.client import ZooKeeperManager
from kazoo.exceptions import AuthFailedError, NoNodeError
from ops.charm import CharmBase
from ops.model import Unit
from tenacity import retry
from tenacity.retry import retry_if_not_result
from tenacity.stop import stop_after_attempt
from tenacity.wait import wait_fixed

logger = logging.getLogger(__name__)

CHARM_KEY = "kafka"
PEER = "cluster"
REL_NAME = "zookeeper"


def zookeeper_connected(charm: CharmBase) -> bool:
    """Flag for if required zookeeper config exists in the relation data.

    Returns:
        True if config exits i.e successful relation. False otherwise
    """
    if not getattr(charm, "kafka_config").zookeeper_config:
        return False

    return True


@retry(
    # retry to give ZK time to update its broker zNodes before failing
    wait=wait_fixed(5),
    stop=stop_after_attempt(3),
    retry_error_callback=(lambda state: state.outcome.result()),
    retry=retry_if_not_result(lambda result: True if result else False),
)
def broker_active(unit: Unit, zookeeper_config: Dict[str, str]) -> bool:
    """Checks ZooKeeper for client connections, checks for specific broker id.

    Args:
        unit: the `Unit` to check connection of
        data: the relation data provided by ZooKeeper

    Returns:
        True if broker id is recognised as active by ZooKeeper. Otherwise False.
    """
    broker_id = unit.name.split("/")[1]
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
        return False

    return f"{chroot}/brokers/ids/{broker_id}" in brokers
