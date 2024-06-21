#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed Machine Operator for Apache Kafka."""

import logging
import time

from charms.data_platform_libs.v0.data_models import TypedCharmBase
from charms.operator_libs_linux.v0 import sysctl
from charms.rolling_ops.v0.rollingops import RollingOpsManager, RunWithLock
from ops import (
    EventBase,
    StatusBase,
)
from ops.main import main

from core.cluster import ClusterState
from core.models import Substrates
from core.structured_config import CharmConfig
from events.balancer import BalancerOperator
from events.broker import BrokerOperator
from literals import (
    CHARM_KEY,
    OS_REQUIREMENTS,
    SUBSTRATE,
    DebugLevel,
    Status,
)
from workload import KafkaWorkload

logger = logging.getLogger(__name__)


class KafkaCharm(TypedCharmBase[CharmConfig]):
    """Charmed Operator for Kafka."""

    config_type = CharmConfig

    def __init__(self, *args):
        super().__init__(*args)
        self.name = CHARM_KEY
        self.substrate: Substrates = SUBSTRATE

        # Common attrs init
        self.state = ClusterState(self, substrate=self.substrate)
        self.sysctl_config = sysctl.Config(name=CHARM_KEY)

        self.workload = KafkaWorkload()  # to be changed?
        self.restart = RollingOpsManager(self, relation="restart", callback=self._restart_broker)

        self.framework.observe(getattr(self.on, "install"), self._on_install)
        self.framework.observe(getattr(self.on, "remove"), self._on_remove)

        # Register roles event handlers after charm ones
        self.broker = BrokerOperator(self)
        self.balancer = BalancerOperator(self)

    def _on_install(self, _) -> None:
        """Handler for `install` event."""
        if not self.workload.install():
            self._set_status(Status.SNAP_NOT_INSTALLED)
            return

        self._set_os_config()

    def _set_os_config(self) -> None:
        """Sets sysctl config."""
        try:
            self.sysctl_config.configure(OS_REQUIREMENTS)
        except (sysctl.ApplyError, sysctl.ValidationError, sysctl.CommandError) as e:
            logger.error(f"Error setting values on sysctl: {e.message}")
            self._set_status(Status.SYSCONF_NOT_POSSIBLE)

    def _on_remove(self, _) -> None:
        """Handler for stop."""
        self.sysctl_config.remove()

    def _set_status(self, key: Status) -> None:
        """Sets charm status."""
        status: StatusBase = key.value.status
        log_level: DebugLevel = key.value.log_level

        getattr(logger, log_level.lower())(status.message)
        self.unit.status = status

    def _restart_broker(self, event: EventBase) -> None:
        """Handler for `rolling_ops` restart events."""
        # only attempt restart if service is already active
        if not self.broker.healthy:
            event.defer()
            return

        self.broker.workload.restart()

        # FIXME: This logic should be improved as part of ticket DPE-3155
        # For more information, please refer to https://warthogs.atlassian.net/browse/DPE-3155
        time.sleep(10.0)

    def _disable_enable_restart_broker(self, event: RunWithLock) -> None:
        """Handler for `rolling_ops` disable_enable restart events."""
        if not self.broker.healthy:
            logger.warning(f"Broker {self.unit.name.split('/')[1]} is not ready restart")
            event.defer()
            return

        self.broker.workload.disable_enable()
        self.broker.workload.start()

        if self.broker.workload.active():
            logger.info(f'Broker {self.unit.name.split("/")[1]} restarted')
        else:
            logger.error(f"Broker {self.unit.name.split('/')[1]} failed to restart")
            return


if __name__ == "__main__":
    main(KafkaCharm)
