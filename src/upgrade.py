# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka in-place upgrades."""

import logging
from typing import TYPE_CHECKING

from charms.data_platform_libs.v0.upgrade import (
    ClusterNotReadyError,
    DataUpgrade,
    DependencyModel,
    UpgradeGrantedEvent,
)
from pydantic import BaseModel
from typing_extensions import override

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)


class KafkaDependencyModel(BaseModel):
    """Model for Kafka Operator dependencies."""

    service: DependencyModel


class KafkaUpgrade(DataUpgrade):
    """Implementation of :class:`DataUpgrade` overrides for in-place upgrades."""

    def __init__(self, charm: "KafkaCharm", **kwargs):
        super().__init__(charm, **kwargs)
        self.charm = charm

    @property
    def idle(self) -> bool:
        """Checks if cluster state is idle.

        Returns:
            True if cluster state is idle. Otherwise False
        """
        return self.cluster_state == "idle"

    @property
    def current_version(self) -> str:
        """Get current Kafka version."""
        dependency_model: DependencyModel = getattr(self.dependency_model, "service")
        return dependency_model.version

    @override
    def pre_upgrade_check(self) -> None:
        default_message = "Pre-upgrade check failed and cannot safely upgrade"
        if not self.charm.healthy:
            raise ClusterNotReadyError(message=default_message, cause="Cluster is not healthy")

    @override
    def build_upgrade_stack(self) -> list[int]:
        upgrade_stack = []
        units = set([self.charm.unit] + list(self.charm.peer_relation.units))  # type: ignore[reportOptionalMemberAccess]
        for unit in units:
            upgrade_stack.append(int(unit.name.split("/")[-1]))

        return upgrade_stack

    @override
    def log_rollback_instructions(self) -> None:
        logger.warning("SOME USEFUL INSTRUCTIONS")  # TODO

    @override
    def _on_upgrade_granted(self, event: UpgradeGrantedEvent) -> None:
        self.charm.snap.stop_snap_service()

        if not self.charm.snap.install():
            logger.error("Unable to install Snap")
            self.set_unit_failed()
            return

        logger.info(f"{self.charm.unit.name} upgrading service...")
        self.charm.snap.restart_snap_service()

        try:
            logger.debug("Running post-upgrade check...")
            self.pre_upgrade_check()

            logger.debug("Marking unit completed...")
            self.set_unit_completed()

            # ensures leader gets it's own relation-changed when it upgrades
            if self.charm.unit.is_leader():
                logger.debug("Re-emitting upgrade-changed on leader...")
                self.on_upgrade_changed(event)
                # If idle run peer config_changed

        except ClusterNotReadyError as e:
            logger.error(e.cause)
            self.set_unit_failed()
