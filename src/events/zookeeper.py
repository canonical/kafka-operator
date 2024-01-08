#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Supporting objects for Kafka-Zookeeper relation."""

import logging
import subprocess
from typing import TYPE_CHECKING, Dict, Set
from ops import Object, RelationChangedEvent, RelationEvent, Unit
from charms.zookeeper.v0.client import QuorumLeaderNotFoundError, ZooKeeperManager

from core.relation_interfaces import ZooKeeperRelation
from core.literals import ZK, Status
from kazoo.exceptions import AuthFailedError, NoNodeError
from tenacity import retry
from tenacity.retry import retry_if_not_result
from tenacity.stop import stop_after_attempt
from tenacity.wait import wait_fixed

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)


class ZooKeeperHandler(Object):
    """Implements the provider-side logic for client applications relating to Kafka."""

    def __init__(self, charm) -> None:
        super().__init__(charm, "zookeeper_client")
        self.charm: "KafkaCharm" = charm
        self.zookeeper_relation = ZooKeeperRelation(charm=charm)

        self.framework.observe(self.charm.on[ZK].relation_created, self._on_zookeeper_created)
        self.framework.observe(self.charm.on[ZK].relation_joined, self._on_zookeeper_changed)
        self.framework.observe(self.charm.on[ZK].relation_changed, self._on_zookeeper_changed)
        self.framework.observe(self.charm.on[ZK].relation_broken, self._on_zookeeper_broken)

    def _on_zookeeper_created(self, _) -> None:
        """Handler for `zookeeper_relation_created` events."""
        if self.model.unit.is_leader():
            self.zookeeper_relation.zookeeper_app_data.update({"chroot": "/" + self.model.app.name})

    def _on_zookeeper_changed(self, event: RelationChangedEvent) -> None:
        """Handler for `zookeeper_relation_created/joined/changed` events, ensuring internal users get created."""
        if not self.zookeeper_connected:
            logger.debug("No information found from ZooKeeper relation")
            self.charm._set_status(Status.ZK_NO_DATA)
            return

        # TLS must be enabled for Kafka and ZK or disabled for both
        if self.charm.cluster.tls_enabled ^ (
            self.zookeeper_config.get("tls", "disabled") == "enabled"
        ):
            event.defer()
            self.charm._set_status(Status.ZK_TLS_MISMATCH)
            return

        # do not create users until certificate + keystores created
        # otherwise unable to authenticate to ZK
        if self.charm.cluster.tls_enabled and not self.charm.cluster.certificate:
            event.defer()
            self.charm._set_status(Status.NO_CERT)
            return

        if not self.charm.cluster.internal_user_credentials and self.model.unit.is_leader():
            # loading the minimum config needed to authenticate to zookeeper
            self.charm.kafka_config.set_zk_jaas_config()
            self.charm.kafka_config.set_server_properties()

            try:
                internal_user_credentials = self.charm._create_internal_credentials()
            except (KeyError, RuntimeError, subprocess.CalledProcessError) as e:
                logger.warning(str(e))
                event.defer()
                return

            # only set to relation data when all set
            for username, password in internal_user_credentials:
                self.charm.cluster.cluster_relation.set_secret(scope="app", key=f"{username}-password", value=password)

        self.charm._on_config_changed(event)

    def _on_zookeeper_broken(self, _: RelationEvent) -> None:
        """Handler for `zookeeper_relation_broken` event, ensuring charm blocks."""
        self.charm.workload.stop()

        logger.info(f'Broker {self.model.unit.name.split("/")[1]} disconnected')
        self.charm._set_status(Status.ZK_NOT_RELATED)

    @property
    def zookeeper_config(self) -> dict[str, str]:
        """The config from current ZooKeeper relations for data necessary for broker connection.

        Returns:
            Dict of ZooKeeeper:
            `username`, `password`, `endpoints`, `chroot`, `connect`, `uris` and `tls`
        """
        zookeeper_config = {}

        if not self.zookeeper_relation.zookeeper_relation:
            return zookeeper_config

        zk_keys = ["username", "password", "endpoints", "chroot", "uris", "tls"]
        missing_config = any(
            self.zookeeper_relation.remote_zookeeper_app_data.get(key, None) is None for key in zk_keys
        )

        # skip if config is missing
        if missing_config:
            return zookeeper_config

        # set if exists
        zookeeper_config.update(self.zookeeper_relation.remote_zookeeper_app_data)

        if zookeeper_config:
            sorted_uris = sorted(
                zookeeper_config["uris"].replace(zookeeper_config["chroot"], "").split(",")
            )
            sorted_uris[-1] = sorted_uris[-1] + zookeeper_config["chroot"]
            zookeeper_config["connect"] = ",".join(sorted_uris)

        return zookeeper_config

    @property
    def zookeeper_related(self) -> bool:
        """Checks if there is a relation with ZooKeeper.

        Returns:
            True if there is a ZooKeeper relation. Otherwise False
        """
        return bool(self.zookeeper_relation.zookeeper_relation)

    @property
    def zookeeper_connected(self) -> bool:
        """Checks if there is an active ZooKeeper relation with all necessary data.

        Returns:
            True if ZooKeeper is currently related with sufficient relation data
                for a broker to connect with. Otherwise False
        """
        if self.zookeeper_config.get("connect", None):
            return True

        return False

    def get_zookeeper_version(self) -> str:
        """Get running zookeeper version.

        Args:
            zookeeper_config: the relation provided by ZooKeeper

        Returns:
            zookeeper version
        """
        config = self.zookeeper_config
        hosts = config.get("endpoints", "").split(",")
        username = config.get("username", "")
        password = config.get("password", "")

        zk = ZooKeeperManager(hosts=hosts, username=username, password=password)

        return zk.get_version()

    def get_active_brokers(self) -> Set[str]:
        """Gets all brokers currently connected to ZooKeeper.

        Args:
            zookeeper_config: the relation data provided by ZooKeeper

        Returns:
            Set of active broker ids
        """
        config = self.zookeeper_config
        chroot = config.get("chroot", "")
        hosts = config.get("endpoints", "").split(",")
        username = config.get("username", "")
        password = config.get("password", "")

        zk = ZooKeeperManager(hosts=hosts, username=username, password=password)
        path = f"{chroot}/brokers/ids/"

        try:
            brokers = zk.leader_znodes(path=path)
        # auth might not be ready with ZK after relation yet
        except (NoNodeError, AuthFailedError, QuorumLeaderNotFoundError) as e:
            logger.debug(str(e))
            return set()

        return brokers

    @retry(
        # retry to give ZK time to update its broker zNodes before failing
        wait=wait_fixed(6),
        stop=stop_after_attempt(10),
        retry_error_callback=(lambda state: state.outcome.result()),  # type: ignore
        retry=retry_if_not_result(lambda result: True if result else False),
    )
    def broker_active(self, unit: Unit, zookeeper_config: Dict[str, str]) -> bool:
        """Checks ZooKeeper for client connections, checks for specific broker id.

        Args:
            unit: the `Unit` to check connection of
            zookeeper_config: the relation provided by ZooKeeper

        Returns:
            True if broker id is recognised as active by ZooKeeper. Otherwise False.
        """
        broker_id = unit.name.split("/")[1]
        brokers = self.get_active_brokers()
        chroot = zookeeper_config.get("chroot", "")
        return f"{chroot}/brokers/ids/{broker_id}" in brokers
