#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Supporting objects for Kafka-Zookeeper relation."""

import logging
import subprocess
from typing import TYPE_CHECKING

from charms.data_platform_libs.v0.data_interfaces import DatabaseRequirerEventHandlers
from ops import Object, RelationChangedEvent, RelationEvent
from ops.pebble import ExecError

from literals import INTERNAL_USERS, ZK, Status

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)


class ZooKeeperHandler(Object):
    """Implements the provider-side logic for client applications relating to Kafka."""

    def __init__(self, charm) -> None:
        super().__init__(charm, "zookeeper_client")
        self.charm: "KafkaCharm" = charm
        self.zookeeper_requires = DatabaseRequirerEventHandlers(
            self.charm, self.charm.state.zookeeper_requires_interface
        )

        self.framework.observe(self.charm.on[ZK].relation_created, self._on_zookeeper_created)
        self.framework.observe(self.charm.on[ZK].relation_joined, self._on_zookeeper_changed)
        self.framework.observe(self.charm.on[ZK].relation_changed, self._on_zookeeper_changed)
        self.framework.observe(self.charm.on[ZK].relation_broken, self._on_zookeeper_broken)

    def _on_zookeeper_created(self, _) -> None:
        """Handler for `zookeeper_relation_created` events."""
        if self.model.unit.is_leader():
            self.charm.state.zookeeper.update({"chroot": "/" + self.model.app.name})

    def _on_zookeeper_changed(self, event: RelationChangedEvent) -> None:
        """Handler for `zookeeper_relation_created/joined/changed` events, ensuring internal users get created."""
        if not self.charm.state.zookeeper.zookeeper_connected:
            self.charm._set_status(Status.ZK_NO_DATA)
            return

        # TLS must be enabled for Kafka and ZK or disabled for both
        if self.charm.state.cluster.tls_enabled ^ self.charm.state.zookeeper.tls:
            event.defer()
            self.charm._set_status(Status.ZK_TLS_MISMATCH)
            return

        # do not create users until certificate + keystores created
        # otherwise unable to authenticate to ZK
        if self.charm.state.cluster.tls_enabled and not self.charm.state.unit_broker.certificate:
            self.charm._set_status(Status.NO_CERT)
            event.defer()
            return

        if not self.charm.state.cluster.internal_user_credentials and self.model.unit.is_leader():
            # loading the minimum config needed to authenticate to zookeeper
            self.charm.config_manager.set_zk_jaas_config()
            self.charm.config_manager.set_server_properties()

            try:
                internal_user_credentials = self._create_internal_credentials()
            except (KeyError, RuntimeError, subprocess.CalledProcessError, ExecError) as e:
                logger.warning(str(e))
                event.defer()
                return

            # only set to relation data when all set
            for username, password in internal_user_credentials:
                self.charm.state.cluster.update({f"{username}-password": password})

        # attempt re-start of Kafka for all units on zookeeper-changed
        # avoids relying on deferred events elsewhere that may not exist after cluster init
        if not self.charm.healthy and self.charm.state.cluster.internal_user_credentials:
            self.charm.on.start.emit()

        self.charm.on.config_changed.emit()

    def _on_zookeeper_broken(self, _: RelationEvent) -> None:
        """Handler for `zookeeper_relation_broken` event, ensuring charm blocks."""
        self.charm.workload.stop()

        logger.info(f'Broker {self.model.unit.name.split("/")[1]} disconnected')
        self.charm._set_status(Status.ZK_NOT_RELATED)

        # Kafka keeps a meta.properties in every log.dir with a unique ClusterID
        # this ID is provided by ZK, and removing it on relation-broken allows
        # re-joining to another ZK cluster.
        for storage in self.charm.model.storages["data"]:
            self.charm.workload.exec(f"rm {storage.location}/meta.properties")

        if not self.charm.unit.is_leader():
            return

        # other charm methods assume credentials == ACLs
        # necessary to clean-up credentials once ZK relation is lost
        for username in self.charm.state.cluster.internal_user_credentials:
            self.charm.state.cluster.update({f"{username}-password": ""})

    def _create_internal_credentials(self) -> list[tuple[str, str]]:
        """Creates internal SCRAM users during cluster start.

        Returns:
            List of (username, password) for all internal users

        Raises:
            RuntimeError if called from non-leader unit
            KeyError if attempted to update non-leader unit
            subprocess.CalledProcessError if command to ZooKeeper failed
        """
        credentials = [
            (username, self.charm.workload.generate_password()) for username in INTERNAL_USERS
        ]
        for username, password in credentials:
            self.charm.auth_manager.add_user(username=username, password=password, zk_auth=True)

        return credentials
