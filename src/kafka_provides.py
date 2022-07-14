#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""KafkaProvider class and methods."""

import logging
import secrets
import string
from typing import List

from ops.charm import RelationBrokenEvent, RelationJoinedEvent
from ops.framework import Object
from ops.model import Relation

REL_NAME = "kafka"
PEER = "cluster"

logger = logging.getLogger(__name__)


class KafkaProvider(Object):
    def __init__(self, charm) -> None:
        super().__init__(charm, "client")

        self.charm = charm

        self.framework.observe(
            self.charm.on[REL_NAME].relation_changed, self._on_client_relation_joined
        )
        self.framework.observe(
            self.charm.on[REL_NAME].relation_broken, self._on_client_relation_broken
        )

    @property
    def app_relation(self) -> Relation:
        return self.charm.model.get_relation(PEER)

    @property
    def client_relations(self) -> List[Relation]:
        return self.charm.model.relations[REL_NAME]

    def _on_client_relation_joined(self, event: RelationJoinedEvent):
        if self.charm.unit.is_leader():
            username = f"relation-{event.relation.id}"
            password = self.app_relation.data[self.charm.app].get(username, self.generate_password())

            self.charm.kafka_config.add_user_to_zookeeper(username=username, password=password)
            self.app_relation.data[self.charm.app].update({username: password})

    def _on_client_relation_broken(self, event: RelationBrokenEvent):
        if self.charm.unit.is_leader():
            username = f"relation-{event.relation.id}"

            self.charm.kafka_config.delete_user_to_zookeeper(username=username)
            self.app_relation.data[self.charm.app].update({username: None})

    @staticmethod
    def generate_password():
        """Creates randomized string for use as app passwords.

        Returns:
            String of 32 randomized letter+digit characters
        """
        return "".join([secrets.choice(string.ascii_letters + string.digits) for _ in range(32)])
