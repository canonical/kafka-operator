#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed Machine Operator for Apache Kafka."""

import logging
import secrets
import string
import subprocess

from charms.kafka.v0.kafka_snap import KafkaSnap
from ops.charm import CharmBase, RelationEvent, RelationJoinedEvent
from ops.framework import EventBase
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    Relation,
    WaitingStatus,
)

from connection_check import broker_active, zookeeper_connected
from kafka_config import KafkaConfig

logger = logging.getLogger(__name__)

CHARM_KEY = "kafka"
PEER = "cluster"
REL_NAME = "zookeeper"


class KafkaCharm(CharmBase):
    """Charmed Operator for Kafka."""

    def __init__(self, *args):
        super().__init__(*args)
        self.name = CHARM_KEY
        self.snap = KafkaSnap()
        self.kafka_config = KafkaConfig(self)

        self.framework.observe(getattr(self.on, "install"), self._on_install)
        self.framework.observe(getattr(self.on, "leader_elected"), self._on_leader_elected)
        self.framework.observe(self.on[REL_NAME].relation_created, self._on_zookeeper_created)
        self.framework.observe(self.on[REL_NAME].relation_joined, self._on_zookeeper_joined)
        self.framework.observe(self.on[REL_NAME].relation_departed, self._on_zookeeper_broken)
        self.framework.observe(self.on[REL_NAME].relation_broken, self._on_zookeeper_broken)

    # TODO: possibly add a 'zookeeper units changed, do something' handler
    # this is because we don't want to restart all Kafka units every time ZK changes units
    # but we do want to ensure Kafka has sufficient ZK connections in config in case of a failure
    # maybe manual action?

    @property
    def peer_relation(self) -> Relation:
        """The Kafka peer relation."""
        return self.model.get_relation(PEER)

    def _on_install(self, _) -> None:
        """Handler for `install` event."""
        if self.snap.install():
            self.kafka_config.set_kafka_opts()
            self.unit.status = WaitingStatus("waiting for zookeeper relation")
        else:
            self.unit.status = BlockedStatus("unable to install kafka snap")

    def _on_leader_elected(self, _) -> None:
        """Handler for `leader_elected` event, ensuring sync_passwords gets set."""
        sync_password = self.kafka_config.sync_password
        if not sync_password:
            self.peer_relation.data[self.app].update(
                {
                    "sync_password": "".join(
                        [secrets.choice(string.ascii_letters + string.digits) for _ in range(32)]
                    )
                }
            )

    def _on_zookeeper_joined(self, event: RelationJoinedEvent) -> None:
        """Handler for `zookeeper_relation_joined` event, ensuring chroot gets set."""
        if self.unit.is_leader():
            event.relation.data[self.app].update({"chroot": "/" + self.app.name})

    def _on_zookeeper_created(self, event: EventBase) -> None:
        """Handler for `zookeeper_relation_created` event."""
        # if missing zookeeper_config, required data might not be set yet
        if not zookeeper_connected(charm=self):
            event.defer()
            return

        # for every new ZK relation, start kafka service
        self._on_start(event=event)

    def _on_zookeeper_broken(self, _: RelationEvent) -> None:
        """Handler for `zookeeper_relation_departed/broken` events."""
        # if missing zookeeper_config, there is no required ZooKeeper relation, block
        if not zookeeper_connected(charm=self):
            logger.info("stopping snap service")
            self.snap.stop_snap_service(snap_service=CHARM_KEY)
            self.unit.status = BlockedStatus("missing required zookeeper relation")

    def _on_start(self, event: EventBase) -> None:
        """Handler for `start` event."""
        self.unit.status = MaintenanceStatus("starting kafka unit")

        # required settings given zookeeper connection config has been created
        self.kafka_config.set_server_properties()
        self.kafka_config.set_jaas_config()

        # do not start units until SCRAM users have been added to ZooKeeper for server-server auth
        if self.unit.is_leader() and self.kafka_config.sync_password:
            try:
                self.kafka_config.add_user_to_zookeeper(username="sync", password=self.kafka_config.sync_password)
                self.peer_relation.data[self.app].update({"broker-creds": "added"})
            except subprocess.CalledProcessError as e:
                logger.exception(str(e))
                # command to add users fails sometimes for unknown reasons. Retry seems to fix it.
                event.defer()
                return

        # for non-leader units
        if not self.peer_relation.data[self.app].get("broker-creds", None):
            logger.debug("broker-creds not yet added to zookeeper")
            event.defer()
            return

        # start kafka service
        start_snap = self.snap.start_snap_service(snap_service=CHARM_KEY)
        if not start_snap:
            self.unit.status = BlockedStatus("unable to start snap")
            return

        # start_snap_service can fail silently, confirm with ZK if kafka is actually connected
        if broker_active(
            unit=self.unit,
            zookeeper_config=self.kafka_config.zookeeper_config,
        ):
            logger.info(f'Broker {self.unit.name.split("/")[1]} connected')
            self.unit.status = ActiveStatus()
        else:
            self.unit.status = BlockedStatus("kafka unit not connected to ZooKeeper")
            return


if __name__ == "__main__":
    main(KafkaCharm)
