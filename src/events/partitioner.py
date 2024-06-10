"""Supporting objects for Broker-Partitioner relation."""

import logging
from typing import TYPE_CHECKING

from ops import EventBase, Object

from literals import PARTITIONER, Status

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)

PARTITIONER_EVENTS = "partitioner-events"


class PartitionerEvents(Object):
    """Implements the provider-side logic for the partitioner."""

    def __init__(self, charm) -> None:
        super().__init__(charm, PARTITIONER_EVENTS)
        self.charm: "KafkaCharm" = charm

        if self.charm.role != PARTITIONER:
            return

        self.framework.observe(self.charm.on.install, self._on_install)
        self.framework.observe(self.charm.on.start, self._on_start)

    def _on_install(self, _) -> None:
        """Handler for `install` event."""
        if not self.charm.workload.install():
            self.charm._set_status(Status.SNAP_NOT_INSTALLED)

    def _on_start(self, _: EventBase) -> None:
        """Handler for `start` event."""
        self.charm._set_status(Status.NOT_IMPLEMENTED)
        self.charm.config_manager.set_cruise_control_properties()

        self.charm.workload.start()
        logger.info("Cruise control started")
