"""Balancer role core charm logic."""

import logging
from subprocess import CalledProcessError
from typing import TYPE_CHECKING

from ops import (
    ActiveStatus,
    ConfigChangedEvent,
    EventBase,
    LeaderElectedEvent,
    Object,
)

from literals import (
    BALANCER,
    BALANCER_TOPICS,
)
from managers.config import BalancerConfigManager
from workload import BalancerWorkload

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)

BALANCER_EVENTS = "balancer-events"


class BalancerOperator(Object):
    """Implements the logic for the balancer."""

    def __init__(self, charm) -> None:
        super().__init__(charm, BALANCER_EVENTS)
        self.charm: "KafkaCharm" = charm

        if BALANCER.value not in self.charm.config.roles:
            return

        self.workload = BalancerWorkload()
        self.config_manager = BalancerConfigManager(
            self.charm.state, self.workload, self.charm.config
        )

        self.framework.observe(self.charm.on.install, self._on_install)
        self.framework.observe(self.charm.on.start, self._on_start)
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

        for topic in BALANCER_TOPICS:
            if topic not in self.workload.run_bin_command(
                "topics",
                [
                    "--list",
                    "--bootstrap-server",
                    f"{self.charm.state.internal_bootstrap_server}",
                    "--command-config",
                    f'{BALANCER.paths["CONF"]}/cruisecontrol.properties',
                ],
            ):
                try:
                    self.workload.run_bin_command(
                        "topics",
                        [
                            "--create",
                            "--topic",
                            topic,
                            "--bootstrap-server",
                            f"{self.charm.state.internal_bootstrap_server}",
                            "--command-config",
                            f'{BALANCER.paths["CONF"]}/cruisecontrol.properties',
                        ],
                    )
                    logger.info(f"Created topic {topic}")
                except CalledProcessError:
                    event.defer()
                    return

        self.workload.start()

        logger.info("Cruise control started")

    def _on_leader_elected(self, event: LeaderElectedEvent) -> None:
        """Handler for `leader-elected` event."""
        if not self.workload.active():
            event.defer()
            return

        self._on_start(event)

    def _on_config_changed(self, event: ConfigChangedEvent) -> None:
        """Handler for `config-changed` event."""
        self._on_start(event)
