#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed Machine Operator for Apache Kafka."""

import logging
import subprocess

from charms.kafka.v0.kafka_snap import KafkaSnap
from charms.rolling_ops.v0.rollingops import RollingOpsManager
from ops.charm import CharmBase, ConfigChangedEvent, RelationEvent, RelationJoinedEvent
from ops.framework import EventBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, Relation, WaitingStatus

from auth import KafkaAuth
from config import KafkaConfig
from literals import CHARM_KEY, PEER, ZK
from provider import KafkaProvider
from utils import broker_active, generate_password, safe_get_file

logger = logging.getLogger(__name__)


class KafkaCharm(CharmBase):
    """Charmed Operator for Kafka."""

    def __init__(self, *args):
        super().__init__(*args)
        self.name = CHARM_KEY
        self.snap = KafkaSnap()
        self.kafka_config = KafkaConfig(self)
        self.provider = KafkaProvider(self)
        self.restart = RollingOpsManager(self, relation="restart", callback=self._restart)

        self.framework.observe(getattr(self.on, "start"), self._on_start)
        self.framework.observe(getattr(self.on, "install"), self._on_install)
        self.framework.observe(getattr(self.on, "leader_elected"), self._on_leader_elected)
        self.framework.observe(getattr(self.on, "config_changed"), self._on_config_changed)

        self.framework.observe(self.on[PEER].relation_changed, self._on_config_changed)

        self.framework.observe(self.on[ZK].relation_joined, self._on_zookeeper_joined)
        self.framework.observe(self.on[ZK].relation_changed, self._on_config_changed)
        self.framework.observe(self.on[ZK].relation_departed, self._on_zookeeper_broken)
        self.framework.observe(self.on[ZK].relation_broken, self._on_zookeeper_broken)

    @property
    def peer_relation(self) -> Relation:
        """The cluster peer relation."""
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
        current_sync_password = self.peer_relation.data[self.app].get("sync_password", None)
        self.peer_relation.data[self.app].update(
            {"sync_password": current_sync_password or generate_password()}
        )

    def _on_zookeeper_joined(self, event: RelationJoinedEvent) -> None:
        """Handler for `zookeeper_relation_joined` event, ensuring chroot gets set."""
        if self.unit.is_leader():
            event.relation.data[self.app].update({"chroot": "/" + self.app.name})

    def _on_zookeeper_broken(self, _: RelationEvent) -> None:
        """Handler for `zookeeper_relation_departed/broken` events."""
        # if missing zookeeper_config, there is no required ZooKeeper relation, block
        self.snap.stop_snap_service(snap_service=CHARM_KEY)
        logger.info(f'Broker {self.unit.name.split("/")[1]} disconnected')
        self.unit.status = BlockedStatus("missing required zookeeper relation")

    def _on_start(self, event: EventBase) -> None:
        """Handler for `start` event."""
        if not self.kafka_config.zookeeper_connected:
            event.defer()
            return

        # required settings given zookeeper connection config has been created
        self.kafka_config.set_jaas_config()
        self.kafka_config.set_server_properties()

        # do not start units until SCRAM users have been added to ZooKeeper for server-server auth
        if self.unit.is_leader() and self.kafka_config.sync_password:
            kafka_auth = KafkaAuth(
                opts=self.kafka_config.extra_args,
                zookeeper=self.kafka_config.zookeeper_config.get("connect", ""),
            )
            try:
                kafka_auth.add_user(
                    username="sync",
                    password=self.kafka_config.sync_password,
                )
                self.peer_relation.data[self.app].update({"broker-creds": "added"})
            except subprocess.CalledProcessError as e:
                # command to add users fails sometimes for unknown reasons. Retry seems to fix it.
                logger.info(str(e))
                event.defer()
                return

        # for non-leader units
        if not self.ready_to_start:
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

    def _on_config_changed(self, event: ConfigChangedEvent) -> None:
        if not self.ready_to_start:
            event.defer()
            return

        properties = safe_get_file(self.kafka_config.properties_filepath)
        if not properties:
            event.defer()
            return

        if set(properties) ^ set(self.kafka_config.server_properties):
            logger.info(
                f"RESTARTING - {set(properties) ^ set(self.kafka_config.server_properties)} are different"
            )
            self.kafka_config.set_server_properties()

            self.on[self.restart.name].acquire_lock.emit()

    def _restart(self, event: EventBase) -> None:
        if not self.ready_to_start:
            event.defer()
            return

        self.snap.restart_snap_service("kafka")

    @property
    def ready_to_start(self):
        if not self.kafka_config.zookeeper_connected or not self.peer_relation.data[self.app].get(
            "broker-creds", None
        ):
            return False

        return True


if __name__ == "__main__":
    main(KafkaCharm)
