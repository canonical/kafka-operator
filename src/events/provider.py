#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""KafkaProvider class and methods."""

import logging
import subprocess
from typing import TYPE_CHECKING

from charms.data_platform_libs.v0.data_interfaces import KafkaProvides, TopicRequestedEvent
from ops.charm import RelationBrokenEvent, RelationCreatedEvent
from ops.framework import Object
from ops.pebble import ExecError

from literals import REL_NAME

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)


class KafkaProvider(Object):
    """Implements the provider-side logic for client applications relating to Kafka."""

    def __init__(self, charm) -> None:
        super().__init__(charm, "kafka_client")
        self.charm: "KafkaCharm" = charm
        self.kafka_provider = KafkaProvides(self.charm, REL_NAME)

        self.framework.observe(self.charm.on[REL_NAME].relation_created, self._on_relation_created)
        self.framework.observe(self.charm.on[REL_NAME].relation_broken, self._on_relation_broken)

        self.framework.observe(
            getattr(self.kafka_provider.on, "topic_requested"), self.on_topic_requested
        )

    def on_topic_requested(self, event: TopicRequestedEvent):
        """Handle the on topic requested event."""
        if not self.charm.healthy:
            event.defer()
            return

        # on all unit update the server properties to enable client listener if needed
        self.charm._on_config_changed(event)

        if not self.charm.unit.is_leader() or not self.charm.state.peer_relation:
            return

        extra_user_roles = event.extra_user_roles or ""
        topic = event.topic or ""
        relation = event.relation
        username = f"relation-{relation.id}"
        password = (
            self.charm.state.cluster.client_passwords.get(username)
            or self.charm.workload.generate_password()
        )
        bootstrap_server = self.charm.state.bootstrap_server
        zookeeper_uris = self.charm.state.zookeeper.connect
        tls = "enabled" if self.charm.state.cluster.tls_enabled else "disabled"

        consumer_group_prefix = (
            event.consumer_group_prefix or f"{username}-" if "consumer" in extra_user_roles else ""
        )

        # catching error here in case listeners not established for bootstrap-server auth
        try:
            self.charm.auth_manager.add_user(
                username=username,
                password=password,
            )
        except (subprocess.CalledProcessError, ExecError):
            logger.warning(f"unable to create user {username} just yet")
            event.defer()
            return

        # non-leader units need cluster_config_changed event to update their super.users
        self.charm.state.cluster.update({username: password})

        self.charm.auth_manager.update_user_acls(
            username=username,
            topic=topic,
            extra_user_roles=extra_user_roles,
            group=consumer_group_prefix,
        )

        # non-leader units need cluster_config_changed event to update their super.users
        self.charm.state.cluster.update({"super-users": self.charm.state.super_users})

        self.kafka_provider.set_bootstrap_server(relation.id, ",".join(bootstrap_server))
        self.kafka_provider.set_consumer_group_prefix(relation.id, consumer_group_prefix)
        self.kafka_provider.set_credentials(relation.id, username, password)
        self.kafka_provider.set_tls(relation.id, tls)
        self.kafka_provider.set_zookeeper_uris(relation.id, zookeeper_uris)
        self.kafka_provider.set_topic(relation.id, topic)

    def _on_relation_created(self, event: RelationCreatedEvent) -> None:
        """Handler for `kafka-client-relation-created` event."""
        self.charm._on_config_changed(event)

    def _on_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Handler for `kafka-client-relation-broken` event.

        Removes relation users from ZooKeeper.

        Args:
            event: the event from a related client application needing a user
        """
        # don't remove anything if app is going down
        if self.charm.app.planned_units == 0:
            return

        if not self.charm.unit.is_leader() or not self.charm.state.peer_relation:
            return

        if not self.charm.healthy:
            event.defer()
            return

        if event.relation.app != self.charm.app or not self.charm.app.planned_units() == 0:
            username = f"relation-{event.relation.id}"
            self.charm.auth_manager.remove_all_user_acls(username=username)
            self.charm.auth_manager.delete_user(username=username)
            # non-leader units need cluster_config_changed event to update their super.users
            # update on the peer relation data will trigger an update of server properties on all units
            self.charm.state.cluster.update({username: ""})

    def update_connection_info(self):
        """Updates all relations with current endpoints, bootstrap-server and tls data.

        If information didn't change, no events will trigger.
        """
        bootstrap_server = self.charm.state.bootstrap_server
        zookeeper_uris = self.charm.state.zookeeper.connect
        tls = "enabled" if self.charm.state.cluster.tls_enabled else "disabled"

        for relation in self.charm.model.relations[REL_NAME]:
            if f"relation-{relation.id}" in self.charm.state.cluster.client_passwords:
                self.kafka_provider.set_bootstrap_server(
                    relation_id=relation.id, bootstrap_server=",".join(bootstrap_server)
                )
                self.kafka_provider.set_tls(relation_id=relation.id, tls=tls)
                self.kafka_provider.set_zookeeper_uris(
                    relation_id=relation.id, zookeeper_uris=zookeeper_uris
                )
