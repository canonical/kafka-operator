"""Supporting objects for Broker-Partitioner relation."""

import logging
from typing import TYPE_CHECKING

from ops import (
    Object,
)
from ops.charm import RelationCreatedEvent

from literals import PARTITIONER, PARTITIONER_SERVICE

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)


class PartitionerProvider(Object):
    """Implements the provider-side logic for the partitioner."""

    def __init__(self, charm) -> None:
        super().__init__(charm, PARTITIONER_SERVICE)
        self.charm: "KafkaCharm" = charm

        self.framework.observe(
            self.charm.on[PARTITIONER_SERVICE].relation_created, self._on_relation_created
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

    def _on_relation_created(self, _) -> None:
        """Handler for `partitioner-relation-created` event."""
        pass

    def _on_relation_changed(self, _) -> None:
        """Handler for `partitioner-relation-created` event."""
        pass

    def _on_relation_broken(self, _) -> None:
        """Handler for `partitioner-relation-created` event."""
        pass


class PartitionerRequirer(Object):
    """Implements the requirer-side logic for the partitioner."""

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

    def _on_relation_created(self, event: RelationCreatedEvent) -> None:
        """Handler for `partitioner-relation-created` event."""
        # if not self.charm.unit.is_leader():
        #     return

        # if not self.charm.healthy:
        #     event.defer()
        #     return

        self.charm.state.partitioner.update({"foo": "bar"})

    def _on_relation_changed(self, _) -> None:
        """Handler for `partitioner-relation-created` event."""
        pass

    def _on_relation_broken(self, _) -> None:
        """Handler for `partitioner-relation-created` event."""
        pass
