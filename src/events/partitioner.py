"""Supporting objects for Broker-Partitioner relation."""

import logging
from typing import TYPE_CHECKING

from charms.data_platform_libs.v0.data_interfaces import (
    RequirerEventHandlers,
)
from ops import EventBase, Object, RelationChangedEvent

from literals import PARTITIONER, PARTITIONER_RELATION, PARTITIONER_SERVICE, Status

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

        self.partitioner_requirer = PartitionerRequirer(self.charm)
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


class PartitionerProvider(Object):
    """Implement the provider-side logic for the partitioner."""

    def __init__(self, charm) -> None:
        super().__init__(charm, PARTITIONER_RELATION)
        self.charm: "KafkaCharm" = charm

        self.framework.observe(
            self.charm.on[PARTITIONER_RELATION].relation_created, self._on_relation_created
        )
        self.framework.observe(
            self.charm.on[PARTITIONER_RELATION].relation_joined, self._on_relation_changed
        )
        self.framework.observe(
            self.charm.on[PARTITIONER_RELATION].relation_changed, self._on_relation_changed
        )
        self.framework.observe(
            self.charm.on[PARTITIONER_RELATION].relation_broken, self._on_relation_broken
        )

    def _on_relation_created(self, _) -> None:
        """Handler for `partitioner-relation-created` event."""
        pass

    def _on_relation_changed(self, _) -> None:
        """Handler for `partitioner-relation-created` event."""
        self.charm.state.partitioner.update({"zookeeper-password": "foo", "kafka-password": "bar"})

    def _on_relation_broken(self, _) -> None:
        """Handler for `partitioner-relation-created` event."""
        pass


class PartitionerRequirerEventHandlers(RequirerEventHandlers):
    """Override abstract event handlers."""

    def _on_relation_changed_event(self, _: RelationChangedEvent) -> None:
        pass

    def _on_secret_changed_event(self, _: RelationChangedEvent) -> None:
        pass


class PartitionerRequirer(Object):
    """Implement the requirer-side logic for the partitioner."""

    def __init__(self, charm) -> None:
        super().__init__(charm, PARTITIONER_SERVICE)
        self.charm: "KafkaCharm" = charm
        self.relation_data = self.charm.state.partitioner

        self.requirer_handler = PartitionerRequirerEventHandlers(
            self.charm,
            self.relation_data.data_interface,  # pyright: ignore[reportGeneralTypeIssues, reportArgumentType]
            PARTITIONER_SERVICE,
        )

        self.framework.observe(
            self.charm.on[PARTITIONER_SERVICE].relation_joined, self._on_relation_changed
        )
        self.framework.observe(
            self.charm.on[PARTITIONER_SERVICE].relation_changed, self._on_relation_changed
        )
        self.framework.observe(
            self.charm.on[PARTITIONER_SERVICE].relation_broken, self._on_relation_broken
        )

    def _on_relation_changed(self, _) -> None:
        """Handler for `partitioner-relation-created` event."""
        pass

    def _on_relation_broken(self, _) -> None:
        """Handler for `partitioner-relation-created` event."""
        pass
