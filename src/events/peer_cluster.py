#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""KafkaProvider class and methods."""

import json
import logging
from typing import TYPE_CHECKING

from charms.data_platform_libs.v0.data_interfaces import RequirerEventHandlers
from ops.charm import RelationChangedEvent, RelationCreatedEvent, RelationEvent, SecretChangedEvent
from ops.framework import Object

from core.cluster import PeerClusterRequirerData
from literals import BROKER

if TYPE_CHECKING:
    from charm import KafkaCharm
    from events.broker import BrokerOperator

logger = logging.getLogger(__name__)


class BalancerEventsHandler(RequirerEventHandlers):
    """Implements the balancer requirer-side logic for peer-cluster relations using secrets."""

    relation_data: PeerClusterRequirerData

    def _on_relation_created_event(self, event: RelationCreatedEvent) -> None:
        """Event emitted when the database relation is created."""
        logger.info("HANDLING RELATION CREATED EVENT")
        super()._on_relation_created_event(event)

    def _on_relation_changed_event(self, event: RelationChangedEvent) -> None:
        """Handler for `balancer-relation-changed` events."""
        diff = self._diff(event)
        if any(newval for newval in diff.added if self.relation_data._is_secret_field(newval)):
            self.relation_data._register_secrets_to_relation(event.relation, diff.added)

    def _on_secret_changed_event(self, _: SecretChangedEvent) -> None:
        pass


class BrokerEventsHandler(Object):
    """Implements the broker provider-side logic for peer-cluster relations."""

    def __init__(self, dependent: "BrokerOperator") -> None:
        super().__init__(dependent, "peer_cluster")
        self.dependent = dependent
        self.charm: "KafkaCharm" = dependent.charm

        self.framework.observe(
            self.charm.on[BROKER.value].relation_changed, self._on_broker_changed
        )
        # ensures data updates, eventually
        self.framework.observe(getattr(self.charm.on, "update_status"), self._on_broker_changed)

    def _on_broker_changed(self, _: RelationEvent) -> None:
        """Generic handler for `broker-relation-*` events."""
        if not self.charm.unit.is_leader():
            return

        # will no-op if relation does not exist
        self.charm.state.balancer.update(
            {
                "username": self.charm.state.balancer.username,
                "password": self.charm.state.balancer.password,
                "bootstrap-server": self.charm.state.balancer.bootstrap_server,
                "zk-uris": self.charm.state.balancer.zk_uris,
                "zk-username": self.charm.state.balancer.zk_username,
                "zk-password": self.charm.state.balancer.zk_password,
                "racks": str(self.charm.state.balancer.racks),
                "broker-capacities": json.dumps(self.charm.state.balancer.broker_capacities),
            }
        )
