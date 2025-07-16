# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka in-place upgrades."""

import abc
import dataclasses
import logging
import time
from typing import TYPE_CHECKING

import charm_refresh

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)


class KafkaUpgradeError(Exception):
    """Exception raised when Kafka upgrade fails."""


@dataclasses.dataclass(eq=False)
class KafkaRefresh(charm_refresh.CharmSpecificCommon, abc.ABC):
    """Base class for Kafka refresh operations."""

    _charm: "KafkaCharm"

    @classmethod
    def is_compatible(
        cls,
        *,
        old_charm_version: charm_refresh.CharmVersion,
        new_charm_version: charm_refresh.CharmVersion,
        old_workload_version: str,
        new_workload_version: str,
    ) -> bool:
        """Checks charm version compatibility."""
        if not super().is_compatible(
            old_charm_version=old_charm_version,
            new_charm_version=new_charm_version,
            old_workload_version=old_workload_version,
            new_workload_version=new_workload_version,
        ):
            return False

        return is_workload_compatible(
            old_workload_version=old_workload_version,
            new_workload_version=new_workload_version,
        )

    def run_pre_refresh_checks_after_1_unit_refreshed(self) -> None:
        """Implement pre-refresh checks after 1 unit refreshed."""
        # TODO: implement pre-refresh checks & preparations before merging or release
        pass


@dataclasses.dataclass(eq=False)
class MachinesKafkaRefresh(KafkaRefresh, charm_refresh.CharmSpecificMachines):
    """Refresh handler for Kafka charm on machines substrate."""

    def refresh_snap(
        self,
        *,
        snap_name: str,
        snap_revision: str,
        refresh: charm_refresh.Machines,
    ) -> None:
        """Refresh the snap for the Kafka charm."""
        self._charm.broker.workload.stop()
        self._charm.balancer.workload.stop()

        revision_before_refresh = self._charm.workload.kafka.revision
        assert snap_revision != revision_before_refresh
        if not self._charm.workload.install():
            logger.exception("Snap refresh failed")

            if self._charm.workload.kafka.revision == revision_before_refresh:
                self._charm.broker.workload.start()
                if self._charm.state.runs_balancer:
                    self._charm.balancer.workload.start()
            else:
                refresh.update_snap_revision()
            raise KafkaUpgradeError

        refresh.update_snap_revision()

        # Post snap refresh logic
        self._charm.broker.config_manager.set_environment()
        if self._charm.state.runs_balancer:
            self._charm.balancer.config_manager.set_environment()

        logger.info(f"{self._charm.unit.name} upgrading service...")
        self._charm.broker.workload.restart()
        if self._charm.state.runs_balancer:
            self._charm.balancer.workload.restart()

        # Allow for some time to settle down
        # FIXME: This logic should be improved as part of ticket DPE-3155
        # For more information, please refer to https://warthogs.atlassian.net/browse/DPE-3155
        time.sleep(20)

        logger.debug("Running post-upgrade check...")
        if not self._charm.broker.healthy:
            logger.error("Cluster is not healthy")

    def run_pre_refresh_checks_after_1_unit_refreshed(self) -> None:
        """Implement pre-refresh checks after 1 unit refreshed."""
        super().run_pre_refresh_checks_after_1_unit_refreshed()


def is_workload_compatible(
    old_workload_version: str,
    new_workload_version: str,
) -> bool:
    """Check if the workload versions are compatible."""
    try:
        old_major, old_minor, *_ = (
            int(component) for component in old_workload_version.split(".")
        )
        new_major, new_minor, *_ = (
            int(component) for component in new_workload_version.split(".")
        )
    except ValueError:
        # Not enough values to unpack or cannot convert
        logger.info(
            "Unable to parse workload versions."
            f"Got {old_workload_version} to {new_workload_version}"
        )
        return False

    if old_major != new_major:
        logger.info(
            "Refreshing to a different major workload is not supported. "
            f"Got {old_major} to {new_major}"
        )
        return False

    if not new_minor >= old_minor:
        logger.info(
            "Downgrading to a previous minor workload is not supported. "
            f"Got {old_major}.{old_minor} to {new_major}.{new_minor}"
        )
        return False

    # TODO: Once more releases are made, MetadataVersion.java on upstream needs to be checked.
    # Rollback is not supported when metadata version has changes. The last field on the version
    # lets us know if there are rollback incompatible changes.
    # Examples:
    # Valid refresh and rollback path
    # IBP_3_9_IV0(21, "3.9", "IV0", false) --> IBP_4_0_IV0(22, "4.0", "IV0", false)
    # Valid refresh, but not rollback path
    # IBP_4_0_IV0(22, "4.0", "IV0", false) --> IBP_4_0_IV1(23, "4.0", "IV1", true)
    #
    # IBP_4_0_IV1 is the latest version as of this writing that breaks rollback compatibility.

    return True
