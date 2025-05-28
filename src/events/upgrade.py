# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka in-place upgrades."""

import logging
import time
from typing import TYPE_CHECKING

from charms.data_platform_libs.v0.upgrade import (
    ClusterNotReadyError,
    DataUpgrade,
    DependencyModel,
    UpgradeGrantedEvent,
)
from charms.operator_libs_linux.v0.sysctl import CalledProcessError
from pydantic import BaseModel
from typing_extensions import override

if TYPE_CHECKING:
    from charm import KafkaCharm
    from events.broker import BrokerOperator

logger = logging.getLogger(__name__)

ROLLBACK_INSTRUCTIONS = """Unit failed to upgrade and requires manual rollback to previous stable version.
    1. Re-run `pre-upgrade-check` action on the leader unit to enter 'recovery' state
    2. Run `juju refresh` to the previously deployed charm revision
"""


class KafkaDependencyModel(BaseModel):
    """Model for Kafka Operator dependencies."""

    kafka_service: DependencyModel


class KafkaUpgrade(DataUpgrade):
    """Implementation of :class:`DataUpgrade` overrides for in-place upgrades."""

    def __init__(self, dependent: "BrokerOperator", **kwargs) -> None:
        super().__init__(dependent.charm, **kwargs)
        self.dependent = dependent
        self.charm: "KafkaCharm" = dependent.charm

    @property
    def idle(self) -> bool:
        """Checks if cluster state is idle.

        Returns:
            True if cluster state is idle. Otherwise False
        """
        return not bool(self.upgrade_stack)

    @property
    def current_version(self) -> str:
        """Get current Kafka version."""
        dependency_model: DependencyModel = getattr(self.dependency_model, "kafka_service")
        return dependency_model.version

    def post_upgrade_check(self) -> None:
        """Runs necessary checks validating the unit is in a healthy state after upgrade."""
        self.pre_upgrade_check()

    @override
    def pre_upgrade_check(self) -> None:
        default_message = "Pre-upgrade check failed and cannot safely upgrade"
        if not self.dependent.healthy:
            raise ClusterNotReadyError(message=default_message, cause="Cluster is not healthy")

    @override
    def build_upgrade_stack(self) -> list[int]:
        upgrade_stack = []
        units = set([self.charm.unit] + list(self.charm.state.peer_relation.units))  # type: ignore[reportOptionalMemberAccess]
        for unit in units:
            upgrade_stack.append(int(unit.name.split("/")[-1]))

        return upgrade_stack

    @override
    def log_rollback_instructions(self) -> None:
        logger.critical(ROLLBACK_INSTRUCTIONS)

    @override
    def _on_upgrade_granted(self, event: UpgradeGrantedEvent) -> None:
        # dependency_model: DependencyModel = getattr(self.dependency_model, "kafka_service")
        # if not verify_requirements(
        #     version=self.zookeeper_current_version,
        #     requirement=dependency_model.dependencies["zookeeper"],
        # ):
        #     logger.error(
        #         "Current ZooKeeper version %s does not meet requirement %s",
        #         self.zookeeper_current_version,
        #         dependency_model.dependencies["zookeeper"],
        #     )
        #     self.set_unit_failed()
        #     return

        self.charm.broker.workload.stop()
        try:
            self.charm.balancer.workload.stop()
        except CalledProcessError:
            # cruise control added in charmed-kafka Rev.37
            pass

        if not self.dependent.workload.install():
            logger.error("Unable to install Snap")
            self.set_unit_failed()
            return

        self.dependent.config_manager.set_environment()
        self.apply_backwards_compatibility_fixes(event)

        logger.info(f"{self.charm.unit.name} upgrading service...")
        self.dependent.workload.restart()

        # Allow for some time to settle down
        # FIXME: This logic should be improved as part of ticket DPE-3155
        # For more information, please refer to https://warthogs.atlassian.net/browse/DPE-3155
        time.sleep(20)

        try:
            logger.debug("Running post-upgrade check...")
            self.post_upgrade_check()

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

    def apply_backwards_compatibility_fixes(self, event) -> None:
        """A range of functions needed for backwards compatibility."""
        logger.info("Applying upgrade fixes")
        # Rev.38 - Create credentials for missing internal user, to reconcile state during upgrades
        # if (
        #     not self.charm.state.cluster.internal_user_credentials
        #     and self.charm.state.zookeeper.zookeeper_connected
        # ):
        #     try:
        #         internal_user_credentials = self.dependent.zookeeper._create_internal_credentials()
        #     except (KeyError, RuntimeError, subprocess.CalledProcessError, ExecError) as e:
        #         logger.warning(str(e))
        #         event.defer()
        #         return

        #     # only set to relation data when all set
        #     for username, password in internal_user_credentials:
        #         self.charm.state.cluster.update({f"{username}-password": password})

        # Rev.179 - broker_capacities needs setting if not already set
        if self.charm.state.runs_broker:
            self.charm.state.unit_broker.update(
                {
                    "cores": str(self.charm.broker.balancer_manager.cores),
                    "rack": self.charm.broker.config_manager.rack,
                }
            )
