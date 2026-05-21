#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka OAuth configuration."""

import logging
from typing import TYPE_CHECKING

from charms.hydra.v0.oauth import ClientConfig, OAuthRequirer
from ops.framework import EventBase, Object

from literals import OAUTH_REL_NAME

if TYPE_CHECKING:
    from charm import KafkaCharm
    from events.broker import BrokerOperator

logger = logging.getLogger(__name__)


class OAuthHandler(Object):
    """Handler for managing oauth relations."""

    def __init__(self, dependent: "BrokerOperator") -> None:
        super().__init__(dependent, "oauth")
        self.dependent = dependent
        self.charm: "KafkaCharm" = dependent.charm

        client_config = ClientConfig("https://kafka.local", "openid email", ["client_credentials"])
        self.oauth = OAuthRequirer(self.charm, client_config, relation_name=OAUTH_REL_NAME)
        self.framework.observe(
            self.charm.on[OAUTH_REL_NAME].relation_changed, self._on_oauth_relation_changed
        )
        self.framework.observe(
            self.charm.on[OAUTH_REL_NAME].relation_broken, self._on_oauth_relation_changed
        )

    def _on_oauth_relation_changed(self, event: EventBase) -> None:
        """Handler for `_on_oauth_relation_changed` event."""
        if not self.charm.unit.is_leader() or not self.charm.state.brokers:
            return
        self.dependent._on_config_changed(event)
