#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""KafkaProvider class and methods."""

import logging
import subprocess
from typing import Callable

from ops import CharmBase, EventBase
from ops.charm import RelationBrokenEvent, RelationCreatedEvent

from charms.data_platform_libs.v0.data_interfaces import KafkaProvides, TopicRequestedEvent
from literals import PEER
from literals import REL_NAME
from utils import generate_password
from new.managers.auth import KafkaAuth
from ..common.charm import PeerRelationMixin
from ..config import ServerConfig
from new.core.models import CharmState
from new.core.workload import AbstractKafkaService

logger = logging.getLogger(__name__)


class KafkaProvider(PeerRelationMixin):
    """Implements the provider-side logic for client applications relating to Kafka."""

    PEER = PEER

    def __init__(
            self, charm: CharmBase,
            state: CharmState, workload: AbstractKafkaService,
            # charm_config: KafkaConfig, auth: KafkaAuth,
            controller: Callable[[EventBase], None]
    ) -> None:
        super().__init__(charm, "kafka_client")

        self.charm = charm
        self.state = state
        self.config = state.config
        self.workload = workload

        self.server_config = ServerConfig(
            self.state.config, self.workload.paths, self.state.cluster, self.state.upgrade,
            self.state.zookeeper, self.state.clients
        )

        self.auth = KafkaAuth(self.server_config, self.workload)

        self.controller = controller

        self.kafka_provider = KafkaProvides(self.charm, REL_NAME)

        self.framework.observe(self.charm.on[REL_NAME].relation_created, self._on_relation_created)
        self.framework.observe(self.charm.on[REL_NAME].relation_broken, self._on_relation_broken)

        self.framework.observe(
            getattr(self.kafka_provider.on, "topic_requested"), self.on_topic_requested
        )

    def on_topic_requested(self, event: TopicRequestedEvent):
        """Handle the on topic requested event."""
        if not self.auth.workload.health():
            event.defer()
            return

        # on all unit update the server properties to enable client listener if needed
        # self.charm._on_config_changed(event)

        if not self.charm.unit.is_leader() or not self.auth.cluster:
            return

        relation = event.relation
        kafka_client = self.auth.server_config.kafka_clients.get(relation.id)

        kafka_client.copy(
            password=kafka_client.password or generate_password(),
            extra_user_roles=kafka_client.extra_user_roles or event.extra_user_roles
        )

        topic = event.topic

        bootstrap_server = self.auth.server_config.bootstrap_server
        zookeeper_uris = self.auth.server_config.zookeeper.connect
        tls = "enabled" if self.auth.cluster.tls.enabled else "disabled"

        consumer_group_prefix = (
            event.consumer_group_prefix or f"{kafka_client.username}-"
            if "consumer" in kafka_client.extra_user_roles else ""
        )

        # catching error here in case listeners not established for bootstrap-server auth
        try:
            self.auth.add_user(
                username=kafka_client.username,
                password=kafka_client.password,
            )
        except subprocess.CalledProcessError:
            logger.warning("unable to create internal user just yet")
            event.defer()
            return

        # CAN WE MOVE ALL DATA BAG UPDATES AT THE END?!?!?!
        # non-leader units need cluster_config_changed event to update their super.users
        self.app_peer_data.update({kafka_client.username: kafka_client.password})

        self.auth.update_user_acls(
            username=kafka_client.username,
            topic=event.topic,
            extra_user_roles=",".join(kafka_client.extra_user_roles),
            group=consumer_group_prefix,
        )

        # non-leader units need cluster_config_changed event to update their super.users
        self.app_peer_data.update({"super-users": self.auth.server_config.super_users})

        self.kafka_provider.set_bootstrap_server(relation.id, ",".join(bootstrap_server))
        self.kafka_provider.set_consumer_group_prefix(relation.id, consumer_group_prefix)
        self.kafka_provider.set_credentials(
            relation.id, kafka_client.username, kafka_client.password
        )
        self.kafka_provider.set_tls(relation.id, tls)
        self.kafka_provider.set_zookeeper_uris(relation.id, zookeeper_uris)
        self.kafka_provider.set_topic(relation.id, topic)

    def _on_relation_created(self, event: RelationCreatedEvent) -> None:
        """Handler for `kafka-client-relation-created` event."""
        self.controller(event)

    def _on_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Handler for `kafka-client-relation-broken` event.

        Removes relation users from ZooKeeper.

        Args:
            event: the event from a related client application needing a user
        """
        # don't remove anything if app is going down
        if self.auth.server_config.charm_config.planned_units == 0:
            return

        if not self.charm.unit.is_leader() or not self.auth.cluster:
            return

        if not self.auth.workload.health():
            event.defer()
            return

        if (event.relation.app != self.charm.app or
                not self.auth.server_config.charm_config.planned_units == 0):
            kafka_client = self.auth.server_config.kafka_clients.get(event.relation.id)

            self.auth.remove_all_user_acls(username=kafka_client.username)
            self.auth.delete_user(username=kafka_client.username)
            # non-leader units need cluster_config_changed event to update their super.users
            # update on the peer relation data will trigger an update of server properties on all unit
            self.app_peer_data.update({kafka_client.username: ""})

    # WHAT DO WE NEED THIS FOR?
    # def update_connection_info(self):
    #    """Updates all relations with current endpoints, bootstrap-server and tls data.
    #
    #    If information didn't change, no events will trigger.
    #    """
    #    bootstrap_server = self.charm.kafka_config.bootstrap_server
    #    zookeeper_uris = self.charm.kafka_config.zookeeper_config.get("connect", "")
    #    tls = "enabled" if self.charm.tls.enabled else "disabled"
    #
    #    for relation in self.charm.model.relations[REL_NAME]:
    #        if self.charm.app_peer_data.get(f"relation-{relation.id}", None):
    #            self.kafka_provider.set_bootstrap_server(
    #                relation_id=relation.id, bootstrap_server=",".join(bootstrap_server)
    #            )
    #            self.kafka_provider.set_tls(relation_id=relation.id, tls=tls)
    #            self.kafka_provider.set_zookeeper_uris(
    #                relation_id=relation.id, zookeeper_uris=zookeeper_uris
    #            )
