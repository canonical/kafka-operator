#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""KafkaProvider class and methods."""

import logging
import secrets
import string
from typing import Dict

from ops.charm import RelationBrokenEvent, RelationJoinedEvent
from ops.framework import Object
from ops.model import Relation

REL_NAME = "kafka"
PEER = "cluster"

logger = logging.getLogger(__name__)


class KafkaProvider(Object):
    """Implements the provider-side logic for client applications relating to Kafka."""

    def __init__(self, charm) -> None:
        super().__init__(charm, "client")

        self.charm = charm

        self.framework.observe(
            self.charm.on[REL_NAME].relation_joined, self._on_client_relation_joined
        )
        self.framework.observe(
            self.charm.on[REL_NAME].relation_broken, self._on_client_relation_broken
        )

    @property
    def app_relation(self) -> Relation:
        """The Kafka cluster's peer relation."""
        return self.charm.model.get_relation(PEER)

    def relation_config(self, relation: Relation) -> Dict[str, str]:
        """Builds necessary relation data for a given relation.

        Args:
            event: the event needing config

        Returns:
            Dict of `username`, `password` and `endpoints` data for the related app
        """
        username = f"relation-{relation.id}"
        password = self.app_relation.data[self.charm.app].get(username, self.generate_password())
        units = set([self.charm.unit] + list(self.app_relation.units))
        endpoints = [self.app_relation.data[unit]["private-address"] for unit in units]

        return {"username": username, "password": password, "endpoints": ",".join(endpoints)}

    def _on_client_relation_joined(self, event: RelationJoinedEvent) -> None:
        """Handler for `relation_joined` events."""
        if not self.charm.unit.is_leader():
            return

        relation_config = self.relation_config(relation=event.relation)

        self.add_user(username=relation_config["username"], password=relation_config["password"])
        event.relation.data[self.charm.app].update(relation_config)

    def _on_client_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Handler for `relation_broken` events."""
        if not self.charm.unit.is_leader():
            return

        relation_config = self.relation_config(relation=event.relation)

        self.delete_user(username=relation_config["username"])

    def add_user(self, username: str, password: str) -> None:
        """Adds/updates users' SCRAM credentials to ZooKeeper.

        Args:
            username: the user's username
            password: the user's password

        Raises:
            subprocess.CalledProcessError: if the command failed
        """
        self.charm.kafka_config.add_user_to_zookeeper(username=username, password=password)
        self.app_relation.data[self.charm.app].update({username: password})

    def delete_user(self, username: str) -> None:
        """Deletes users' SCRAM credentials from ZooKeeper.

        Args:
            username: the user's username

        Raises:
            subprocess.CalledProcessError: if the command failed
        """
        self.charm.kafka_config.delete_user_from_zookeeper(username=username)
        self.app_relation.data[self.charm.app].update({username: ""})

    @staticmethod
    def generate_password():
        """Creates randomized string for use as app passwords.

        Returns:
            String of 32 randomized letter+digit characters
        """
        return "".join([secrets.choice(string.ascii_letters + string.digits) for _ in range(32)])
