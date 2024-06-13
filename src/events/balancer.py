"""Supporting objects for Broker-Balancer relation."""

import logging
from typing import TYPE_CHECKING

from ops import EventBase, Object

from literals import BALANCER, Status
from managers.config import BalancerConfigManager

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)

BALANCER_EVENTS = "balancer-events"


class BalancerEvents(Object):
    """Implements the provider-side logic for the balancer."""

    def __init__(self, charm) -> None:
        super().__init__(charm, BALANCER_EVENTS)
        self.charm: "KafkaCharm" = charm

        if self.charm.role != BALANCER:
            return
        self.config_manager = BalancerConfigManager(
            self.charm.state, self.charm.workload, self.charm.config
        )
        self.framework.observe(self.charm.on.install, self._on_install)
        self.framework.observe(self.charm.on.start, self._on_start)

    def _on_install(self, _) -> None:
        """Handler for `install` event."""
        if not self.charm.workload.install():
            self.charm._set_status(Status.SNAP_NOT_INSTALLED)

    def _on_start(self, _: EventBase) -> None:
        """Handler for `start` event."""
        self.charm._set_status(Status.NOT_IMPLEMENTED)
        self.config_manager.set_cruise_control_properties()

        self.charm.workload.start()
        logger.info("Cruise control started")
