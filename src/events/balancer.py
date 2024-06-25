"""Balancer role core charm logic."""

import logging
from subprocess import CalledProcessError
from typing import TYPE_CHECKING

from ops import (
    ActiveStatus,
    ConfigChangedEvent,
    LeaderElectedEvent,
    Object,
    StartEvent,
)

from events.registry import BalancerEvents, BalancerStartEvent
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

    on = BalancerEvents()  # type: ignore

    def __init__(self, charm) -> None:
        super().__init__(charm, BALANCER_EVENTS)
        self.charm: "KafkaCharm" = charm

        if BALANCER.value not in self.charm.config.roles:
            return

        self.workload = BalancerWorkload()
        self.config_manager = BalancerConfigManager(
            self.charm.state, self.workload, self.charm.config
        )

        ## Charm-level events

        self.framework.observe(self.charm.on.install, self._on_install)
        self.framework.observe(self.charm.on.start, self._on_start)
        self.framework.observe(
            self.charm.on[BALANCER.value].relation_changed, self._on_config_changed
        )

        ## Role-level events

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)

    def _on_install(self, _) -> None:
        """Handler for `install` event."""
        self.config_manager.set_environment()

    def _on_start(self, _: StartEvent) -> None:
        """Handler for `start` event."""
        if not self.charm.unit.is_leader():
            self.workload.stop()
            logger.info("Cruise control stopped")
            return

        self.charm._set_status(self.charm.state.ready_to_balance)

        if not isinstance(self.charm.unit.status, ActiveStatus):
            BalancerStartEvent(self.on.handle).defer()
            return

        self.config_manager.set_cruise_control_properties()
        self.config_manager.set_broker_capacities()
        self.config_manager.set_cruise_control_jaas_config()

        self.config_manager.set_environment()
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
                opts=[
                    self.config_manager.kafka_opts,
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
                        opts=[
                            self.config_manager.kafka_opts,
                        ],
                    )
                except CalledProcessError:
                    BalancerStartEvent(self.on.handle).defer()
                    return

        self.workload.start()

        logger.info("Cruise control started")

    def _on_leader_elected(self, event: LeaderElectedEvent) -> None:
        """Handler for `leader-elected` event."""
        if not self.workload.active():
            event.defer()
            return

        self.on.start.emit()

    def _on_config_changed(self, _: ConfigChangedEvent) -> None:
        """Handler for `config-changed` event."""
        self.on.start.emit()
