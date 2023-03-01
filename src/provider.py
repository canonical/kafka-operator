#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""KafkaProvider class and methods."""

import logging

from charms.data_platform_libs.v0.data_interfaces import KafkaProvides, TopicRequestedEvent
from ops.charm import RelationBrokenEvent
from ops.framework import Object
from ops.model import Relation

from auth import KafkaAuth
from config import KafkaConfig
from literals import PEER, REL_NAME
from utils import generate_password

logger = logging.getLogger(__name__)


class KafkaProvider(Object):
    """Implements the provider-side logic for client applications relating to Kafka."""

    def __init__(self, charm) -> None:
        super().__init__(charm, "kafka_client")
        self.charm = charm
        self.kafka_config = KafkaConfig(self.charm)
        self.kafka_auth = KafkaAuth(
            charm,
            opts=self.kafka_config.auth_args,
            zookeeper=self.kafka_config.zookeeper_config.get("connect", ""),
        )

        self.kafka_provider = KafkaProvides(self.charm, REL_NAME)

        self.framework.observe(self.charm.on[REL_NAME].relation_broken, self._on_relation_broken)

        self.framework.observe(
            getattr(self.kafka_provider.on, "topic_requested"), self.on_topic_requested
        )

    def on_topic_requested(self, event: TopicRequestedEvent):
        """Handle the on topic requested event."""
        if not self.charm.ready_to_start:
            logger.debug("cannot add user, ZooKeeper not yet connected")
            event.defer()
            return

        if not self.charm.kafka_config.zookeeper_connected:
            logger.debug("cannot update ACLs, ZooKeeper not yet connected")
            event.defer()
            return

        # on all unit update the server properties to enable client listener if needed
        self.charm._on_config_changed(event)

        if not self.charm.unit.is_leader():
            return

        extra_user_roles = event.extra_user_roles or ""
        topic = event.topic or ""
        relation = event.relation
        username = f"relation-{relation.id}"
        password = self.peer_relation.data[self.charm.app].get(username) or generate_password()
        bootstrap_server = self.charm.kafka_config.bootstrap_server
        zookeeper_uris = self.charm.kafka_config.zookeeper_config.get("connect", "")
        tls = "enabled" if self.charm.tls.enabled else "disabled"

        consumer_group_prefix = (
            event.consumer_group_prefix or f"{username}-" if "consumer" in extra_user_roles else ""
        )

        self.kafka_auth.add_user(
            username=username,
            password=password,
        )

        # non-leader units need cluster_config_changed event to update their super.users
        self.peer_relation.data[self.charm.app].update({username: password})

        self.kafka_auth.load_current_acls()

        self.kafka_auth.update_user_acls(
            username=username,
            topic=topic,
            extra_user_roles=extra_user_roles,
            group=consumer_group_prefix,
        )

        # non-leader units need cluster_config_changed event to update their super.users
        self.peer_relation.data[self.charm.app].update(
            {"super-users": self.kafka_config.super_users}
        )

        self.kafka_provider.set_bootstrap_server(relation.id, ",".join(bootstrap_server))
        self.kafka_provider.set_consumer_group_prefix(relation.id, consumer_group_prefix)
        self.kafka_provider.set_credentials(relation.id, username, password)
        self.kafka_provider.set_tls(relation.id, tls)
        self.kafka_provider.set_zookeeper_uris(relation.id, zookeeper_uris)
        self.kafka_provider.set_topic(relation.id, topic)

    @property
    def peer_relation(self) -> Relation:
        """The Kafka cluster's peer relation."""
        return self.charm.model.get_relation(PEER)

    def _on_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Handler for `kafka-client-relation-broken` event.

        Removes relation users from ZooKeeper.

        Args:
            event: the event from a related client application needing a user
        """
        if not self.charm.unit.is_leader():
            return

        if not self.charm.ready_to_start:
            logger.debug("cannot remove user, ZooKeeper not yet connected")
            event.defer()
            return

        if event.relation.app != self.charm.app or not self.charm.app.planned_units() == 0:

            self.kafka_auth.load_current_acls()
            username = f"relation-{event.relation.id}"
            self.kafka_auth.remove_all_user_acls(
                username=username,
            )
            self.kafka_auth.delete_user(username=username)
            # non-leader units need cluster_config_changed event to update their super.users
            # update on the peer relation data will trigger an update of server properties on all unit
            self.peer_relation.data[self.charm.app].update({username: ""})

    def update_connection_info(self):
        """Updates all relations with current endpoints, bootstrap-server and tls data.

        If information didn't change, no events will trigger.
        """
        bootstrap_server = self.charm.kafka_config.bootstrap_server
        zookeeper_uris = self.charm.kafka_config.zookeeper_config.get("connect", "")
        tls = "enabled" if self.charm.tls.enabled else "disabled"

        for relation in self.charm.model.relations[REL_NAME]:
            if self.charm.app_peer_data.get(f"relation-{relation.id}", None):
                self.kafka_provider.set_bootstrap_server(
                    relation_id=relation.id, bootstrap_server=",".join(bootstrap_server)
                )
                self.kafka_provider.set_tls(relation_id=relation.id, tls=tls)
                self.kafka_provider.set_zookeeper_uris(
                    relation_id=relation.id, zookeeper_uris=zookeeper_uris
                )
