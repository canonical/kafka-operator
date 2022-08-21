#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""KafkaProvider class and methods."""

import logging
from typing import Dict

from ops.charm import (
    RelationBrokenEvent,
    RelationChangedEvent,
    RelationCreatedEvent,
    RelationEvent,
)
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
            opts=self.kafka_config.extra_args,
            zookeeper=self.kafka_config.zookeeper_config.get("connect", ""),
        )

        self.framework.observe(self.charm.on[REL_NAME].relation_created, self._on_relation_created)
        self.framework.observe(self.charm.on[REL_NAME].relation_changed, self.update_acls)
        self.framework.observe(self.charm.on[REL_NAME].relation_broken, self._on_relation_broken)

    @property
    def peer_relation(self) -> Relation:
        """The Kafka cluster's peer relation."""
        return self.charm.model.get_relation(PEER)

    def requirer_relation_config(self, event: RelationEvent) -> Dict[str, str]:
        """Builds necessary client relation data for a given relation event.

        Args:
            event: the event needing config

        Returns:
            Dict with keys `topic` and `extra_user_roles`
        """
        return {
            "extra_user_roles": event.relation.data[event.app].get("extra-user-roles", ""),
            "topic": event.relation.data[event.app].get("topic"),
        }

    def provider_relation_config(self, event: RelationEvent) -> Dict[str, str]:
        """Builds necessary provider relation data for a given relation event.

        Args:
            event: the event needing config

        Returns:
            Dict of `username`, `password` and `endpoints` data for the related app
        """
        relation = event.relation

        username = f"relation-{relation.id}"
        password = self.peer_relation.data[self.charm.app].get(username) or generate_password()
        bootstrap_server = self.charm.kafka_config.bootstrap_server
        endpoints = [server.split(":")[0] for server in bootstrap_server]
        zookeeper_uris = self.charm.kafka_config.zookeeper_config.get("connect", "")

        relation_config = {
            "username": username,
            "password": password,
            "endpoints": ",".join(endpoints),
            "uris": ",".join(bootstrap_server),
            "zookeeper-uris": zookeeper_uris,
            "consumer-group-prefix": "",
        }

        # only set this if `consumer` is set to avoid missing information
        if "consumer" in event.relation.data[event.app].get("extra-user-roles", ""):
            relation_config["consumer-group-prefix"] = f"{username}-"

        return relation_config

    def update_acls(self, event: RelationChangedEvent) -> None:
        """Updates cluster ACLs for a given event relation to match client relation data.

        Args:
            event: the event from a related client application needing ACLs
        """
        if not self.charm.unit.is_leader():
            return

        if not self.charm.kafka_config.zookeeper_connected:
            logger.debug("cannot update ACLs, ZooKeeper not yet connected")
            event.defer()
            return

        provider_relation_config = self.provider_relation_config(event=event)
        requirer_relation_config = self.requirer_relation_config(event=event)

        self.kafka_auth.load_current_acls()

        self.kafka_auth.update_user_acls(
            username=provider_relation_config["username"],
            group=provider_relation_config.get("consumer-group-prefix"),
            **requirer_relation_config,
        )

        # non-leader units need cluster_config_changed event to update their super.users
        self.charm.model.get_relation(PEER).data[self.charm.app].update(
            {"super-users": self.kafka_config.super_users}
        )

        event.relation.data[self.charm.app].update(provider_relation_config)

    def _on_relation_created(self, event: RelationCreatedEvent) -> None:
        """Handler for `kafka-client-relation-created` event.

        Adds new relation users to ZooKeeper.

        Args:
            event: the event from a related client application needing a user
        """
        if not self.charm.unit.is_leader():
            return

        if not self.charm.ready_to_start:
            logger.debug("cannot add user, ZooKeeper not yet connected")
            event.defer()
            return

        provider_relation_config = self.provider_relation_config(event=event)

        self.kafka_auth.add_user(
            username=provider_relation_config["username"],
            password=provider_relation_config["password"],
        )

        # non-leader units need cluster_config_changed event to update their super.users
        self.charm.model.get_relation(PEER).data[self.charm.app].update(
            {provider_relation_config["username"]: provider_relation_config["password"]}
        )

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

        if (
            event.relation.app != self.charm.app or not self.charm.app.planned_units() == 0
        ):  # avoid on own charm during teardown
            provider_relation_config = self.provider_relation_config(event=event)

            self.kafka_auth.load_current_acls()

            self.kafka_auth.remove_all_user_acls(
                username=provider_relation_config["username"],
            )
            self.kafka_auth.delete_user(username=provider_relation_config["username"])

            # non-leader units need cluster_config_changed event to update their super.users
            self.charm.model.get_relation(PEER).data[self.charm.app].update(
                {provider_relation_config["username"]: ""}
            )
