# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka OAuth configuration."""

import logging
from typing import TYPE_CHECKING

from charms.hydra.v0.oauth import ClientConfig, OAuthRequirer
from ops.charm import (
    RelationBrokenEvent,
    RelationCreatedEvent,
)
from ops.framework import Object

from literals import OAUTH_REL_NAME

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)


class OAuthHandler(Object):
    """Handler for managing oauth relations."""

    def __init__(self, charm):
        super().__init__(charm, "oauth")
        self.charm: "KafkaCharm" = charm

        client_config = ClientConfig("https://kafka.local", "openid email", ["client_credentials"])
        self.oauth = OAuthRequirer(charm, client_config, relation_name=OAUTH_REL_NAME)
        self.framework.observe(
            self.charm.on[OAUTH_REL_NAME].relation_created, self._on_oauth_relation_created
        )
        self.framework.observe(
            self.charm.on[OAUTH_REL_NAME].relation_changed, self.charm._on_config_changed
        )
        self.framework.observe(
            self.charm.on[OAUTH_REL_NAME].relation_broken, self._on_oauth_relation_broken
        )

    def _on_oauth_relation_created(self, event: RelationCreatedEvent) -> None:
        """Handler for `oauth_relation_created` event."""
        if not self.charm.unit.is_leader() or not self.charm.state.brokers:
            return
        # TODO: create oauth truststore

    def _on_oauth_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Handler for `_on_oauth_relation_broken` event."""
        if not self.charm.unit.is_leader() or not self.charm.state.brokers:
            return
        # TODO: remove oauth truststore
        self.charm._on_config_changed(event)
