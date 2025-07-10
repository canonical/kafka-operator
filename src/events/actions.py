#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Event handlers for Juju Actions."""

import logging
from typing import TYPE_CHECKING

from ops.charm import ActionEvent
from ops.framework import Object

if TYPE_CHECKING:
    from charm import KafkaCharm
    from events.broker import BrokerOperator

logger = logging.getLogger(__name__)


class ActionEvents(Object):
    """Event handlers for Juju Actions."""

    def __init__(self, dependent: "BrokerOperator") -> None:
        super().__init__(dependent, "action_events")
        self.dependent = dependent
        self.charm: "KafkaCharm" = dependent.charm

        self.framework.observe(
            getattr(self.charm.on, "get_listeners_action"), self._get_listeners_action
        )

    def _get_listeners_action(self, event: ActionEvent) -> None:
        """Handler for get-listeners action."""
        listeners = self.dependent.config_manager.all_listeners

        result = {}
        for listener in listeners:
            key = listener.name.replace("_", "-").lower()
            result.update(
                {
                    key: {
                        "name": listener.name,
                        "scope": listener.scope,
                        "port": listener.port,
                        "protocol": listener.protocol,
                        "auth-mechanism": listener.mechanism,
                        "advertised-listener": listener.advertised_listener,
                    }
                }
            )

        event.set_results(result)
