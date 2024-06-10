"""Supporting objects for Broker-Partitioner relation."""

import logging
from typing import TYPE_CHECKING

from charms.data_platform_libs.v0.data_interfaces import (
    RequirerEventHandlers,
)
from ops import Object, RelationChangedEvent

from literals import PARTITIONER, PARTITIONER_SERVICE

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)


class PartitionerProvider(Object):
    """Implement the provider-side logic for the partitioner."""

    def __init__(self, charm) -> None:
        super().__init__(charm, PARTITIONER)
        self.charm: "KafkaCharm" = charm

        self.framework.observe(
            self.charm.on[PARTITIONER].relation_created, self._on_relation_created
        )
        self.framework.observe(
            self.charm.on[PARTITIONER].relation_joined, self._on_relation_changed
        )
        self.framework.observe(
            self.charm.on[PARTITIONER].relation_changed, self._on_relation_changed
        )
        self.framework.observe(
            self.charm.on[PARTITIONER].relation_broken, self._on_relation_broken
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
