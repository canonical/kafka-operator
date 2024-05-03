#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""KafkaProvider class and methods."""

import logging
import subprocess  # nosec B404
from typing import TYPE_CHECKING

from charms.data_platform_libs.v0.data_interfaces import (
    KafkaProviderEventHandlers,
    TopicRequestedEvent,
)
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
        self.kafka_provider = KafkaProviderEventHandlers(
            self.charm, self.charm.state.client_provider_interface
        )

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

        requesting_client = None
        for client in self.charm.state.clients:
            if event.relation == client.relation:
                requesting_client = client
                break

        if not requesting_client:
            event.defer()
            return

        password = client.password or self.charm.workload.generate_password()

        # catching error here in case listeners not established for bootstrap-server auth
        try:
            self.charm.auth_manager.add_user(
                username=client.username,
                password=password,
            )
        except (subprocess.CalledProcessError, ExecError):
            logger.warning(f"unable to create user {client.username} just yet")
            event.defer()
            return

        # non-leader units need cluster_config_changed event to update their super.users
        self.charm.state.cluster.update({client.username: password})

        self.charm.auth_manager.update_user_acls(
            username=client.username,
            topic=client.topic,
            extra_user_roles=client.extra_user_roles,
            group=client.consumer_group_prefix,
        )

        # non-leader units need cluster_config_changed event to update their super.users
        self.charm.state.cluster.update({"super-users": self.charm.state.super_users})

        self.charm.update_client_data()

    def _on_relation_created(self, event: RelationCreatedEvent) -> None:
        """Handler for `kafka-client-relation-created` event."""
        self.charm._on_config_changed(event)

    def _on_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Handler for `kafka-client-relation-broken` event.

        Removes relation users from ZooKeeper.

        Args:
            event: the event from a related client application needing a user
        """
        if (
            # don't remove anything if app is going down
            self.charm.app.planned_units == 0
            or not self.charm.unit.is_leader()
            or not self.charm.state.cluster
        ):
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

        self.charm.update_client_data()
