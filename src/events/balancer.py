"""Balancer role core charm logic."""

import logging
from subprocess import CalledProcessError
from typing import TYPE_CHECKING

from ops import (
    ActiveStatus,
    ConfigChangedEvent,
    EventBase,
    Object,
    UpdateStatusEvent,
)

from literals import (
    BALANCER,
    Status,
)
from managers.balancer import BalancerManager
from managers.config import BalancerConfigManager
from workload import BalancerWorkload

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)


class BalancerOperator(Object):
    """Implements the logic for the balancer."""

    def __init__(self, charm) -> None:
        super().__init__(charm, BALANCER.value)
        self.charm: "KafkaCharm" = charm

        self.workload = BalancerWorkload()

        # Fast exit after workload instantiation, but before any event observer
        if BALANCER.value not in self.charm.config.roles:
            return

        self.config_manager = BalancerConfigManager(
            self.charm.state, self.workload, self.charm.config
        )
        self.balancer_manager = BalancerManager(self)

        self.framework.observe(self.charm.on.install, self._on_install)
        self.framework.observe(self.charm.on.start, self._on_start)
        self.framework.observe(self.charm.on.update_status, self._on_update_status)
        self.framework.observe(
            self.charm.on[BALANCER.value].relation_changed, self._on_config_changed
        )

    def _on_install(self, _) -> None:
        """Handler for `install` event."""
        self.config_manager.set_environment()

    def _on_start(self, event: EventBase) -> None:
        """Handler for `start` event."""
        if not self.charm.unit.is_leader():
            self.workload.stop()
            return

        self.charm._set_status(self.charm.state.ready_to_start)

        if not isinstance(self.charm.unit.status, ActiveStatus):
            event.defer()
            return

        self.config_manager.set_cruise_control_properties()
        self.config_manager.set_broker_capacities()

        try:
            self.balancer_manager.create_internal_topics()
        except CalledProcessError:
            event.defer()
            return

        self.workload.start()

        logger.info("Cruise control started")

        self.charm.on.update_status.emit()

    def _on_config_changed(self, event: ConfigChangedEvent) -> None:
        """Handler for `config-changed` event."""
        self._on_start(event)

    @property
    def healthy(self) -> bool:
        """Checks and updates various charm lifecycle states.

        Is slow to fail due to retries, to be used sparingly.

        Returns:
            True if service is alive and active. Otherwise False
        """
        self.charm._set_status(self.charm.state.ready_to_start)
        if not isinstance(self.charm.unit.status, ActiveStatus):
            return False

        if not self.workload.active():
            self.charm._set_status(Status.SNAP_NOT_RUNNING)
            return False

        return True

    def _on_update_status(self, _: UpdateStatusEvent) -> None:
        """Handler for `update-status` events."""
        if not self.healthy:
            return

        if not self.charm.state.zookeeper.broker_active():
            self.charm._set_status(Status.ZK_NOT_CONNECTED)
            return

        self.charm._set_status(Status.ACTIVE)
