"""Supporting objects for Broker-Balancer relation."""

import logging
from typing import TYPE_CHECKING

from charms.data_platform_libs.v0.data_interfaces import (
    RequirerEventHandlers,
)
from ops import EventBase, Object, RelationChangedEvent, RelationCreatedEvent

from literals import (
    ADMIN_USER,
    BALANCER,
    BALANCER_RELATION,
    BALANCER_SERVICE,
    BALANCER_TOPIC,
    Status,
)

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)

BALANCER_EVENTS = "balancer-events"


class BalancerEvents(Object):
    """Implements the logic for the balancer."""

    def __init__(self, charm) -> None:
        super().__init__(charm, BALANCER_EVENTS)
        self.charm: "KafkaCharm" = charm

        if self.charm.role != BALANCER:
            return

        self.balancer_requirer = BalancerRequirer(self.charm)

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


class BalancerProvider(Object):
    """Implement the provider-side logic for the balancer."""

    def __init__(self, charm) -> None:
        super().__init__(charm, BALANCER_RELATION)
        self.charm: "KafkaCharm" = charm

        self.framework.observe(
            self.charm.on[BALANCER_RELATION].relation_created, self._on_relation_created
        )
        self.framework.observe(
            self.charm.on[BALANCER_RELATION].relation_joined, self._on_relation_changed
        )
        self.framework.observe(
            self.charm.on[BALANCER_RELATION].relation_changed, self._on_relation_changed
        )
        self.framework.observe(
            self.charm.on[BALANCER_RELATION].relation_broken, self._on_relation_broken
        )

    def _on_relation_created(self, _) -> None:
        """Handler for `balancer-relation-created` event."""
        pass

    def _on_relation_changed(self, _) -> None:
        """Handler for `balancer-relation-created` event."""
        self.charm.update_client_data()

    def _on_relation_broken(self, _) -> None:
        """Handler for `balancer-relation-created` event."""
        pass


class BalancerRequirerEventHandlers(RequirerEventHandlers):
    """Override abstract event handlers."""

    def _on_relation_created_event(self, event: RelationCreatedEvent) -> None:
        """Event emitted when the database relation is created."""
        super()._on_relation_created_event(event)
        event_data = {"extra-user-roles": ADMIN_USER, "topic": BALANCER_TOPIC}
        self.relation_data.update_relation_data(event.relation.id, event_data)

    def _on_relation_changed_event(self, _: RelationChangedEvent) -> None:
        pass

    def _on_secret_changed_event(self, _: RelationChangedEvent) -> None:
        pass


class BalancerRequirer(Object):
    """Implement the requirer-side logic for the balancer."""

    def __init__(self, charm) -> None:
        super().__init__(charm, BALANCER_SERVICE)
        self.charm: "KafkaCharm" = charm
        self.relation_data = self.charm.state.balancer

        self.requirer_handler = BalancerRequirerEventHandlers(
            self.charm,
            self.relation_data.data_interface,  # pyright: ignore[reportGeneralTypeIssues, reportArgumentType]
            BALANCER_SERVICE,
        )

        self.framework.observe(
            self.charm.on[BALANCER_SERVICE].relation_joined, self._on_relation_changed
        )
        self.framework.observe(
            self.charm.on[BALANCER_SERVICE].relation_changed, self._on_relation_changed
        )
        self.framework.observe(
            self.charm.on[BALANCER_SERVICE].relation_broken, self._on_relation_broken
        )

    def _on_relation_changed(self, _) -> None:
        """Handler for `balancer-relation-created` event."""
        pass

    def _on_relation_broken(self, _) -> None:
        """Handler for `balancer-relation-created` event."""
        pass
