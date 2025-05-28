#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed Machine Operator for Apache Kafka."""

import logging
import time

import ops
from charms.data_platform_libs.v0.data_models import TypedCharmBase
from charms.grafana_agent.v0.cos_agent import COSAgentProvider
from charms.operator_libs_linux.v0 import sysctl
from charms.rolling_ops.v0.rollingops import RollingOpsManager, RunWithLock
from ops import (
    CollectStatusEvent,
    EventBase,
    StatusBase,
)

from core.cluster import ClusterState
from core.models import Substrates
from core.structured_config import CharmConfig
from events.balancer import BalancerOperator
from events.broker import BrokerOperator
from events.peer_cluster import PeerClusterEventsHandler
from events.tls import TLSHandler
from literals import (
    CHARM_KEY,
    JMX_CC_PORT,
    JMX_EXPORTER_PORT,
    LOGS_RULES_DIR,
    METRICS_RULES_DIR,
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
        self.pending_inactive_statuses: list[Status] = []

        # Common attrs init
        self.state = ClusterState(self, substrate=self.substrate)
        self.sysctl_config = sysctl.Config(name=CHARM_KEY)

        self.workload = KafkaWorkload()  # Will be re-instantiated for each role.
        self.restart = RollingOpsManager(self, relation="restart", callback=self._restart_broker)

        self._grafana_agent = COSAgentProvider(
            self,
            metrics_endpoints=[
                # Endpoint for the kafka and jmx exporters
                # See https://github.com/canonical/charmed-kafka-snap for details
                {"path": "/metrics", "port": JMX_EXPORTER_PORT},
                {"path": "/metrics", "port": JMX_CC_PORT},
            ],
            metrics_rules_dir=METRICS_RULES_DIR,
            logs_rules_dir=LOGS_RULES_DIR,
            log_slots=[f"{self.workload.SNAP_NAME}:{slot}" for slot in self.workload.LOG_SLOTS],
        )

        self.framework.observe(getattr(self.on, "install"), self._on_install)
        self.framework.observe(getattr(self.on, "remove"), self._on_remove)
        self.framework.observe(getattr(self.on, "config_changed"), self._on_roles_changed)
        self.framework.observe(self.on.collect_unit_status, self._on_collect_status)
        self.framework.observe(self.on.collect_app_status, self._on_collect_status)

        # peer-cluster events are shared between all roles, so necessary to init here to avoid instantiating multiple times
        self.peer_cluster = PeerClusterEventsHandler(self)

        # Register roles event handlers after global ones, so that they get the priority.
        self.broker = BrokerOperator(self)
        self.balancer = BalancerOperator(self)

        self.tls = TLSHandler(self)

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
        self.pending_inactive_statuses.append(key)

    def _on_roles_changed(self, _):
        """Handler for `config_changed` events.

        This handler is in charge of stopping the workloads, since the sub-operators would not
        be instantiated if roles are changed.
        """
        if (
            not (self.state.runs_broker or self.state.runs_controller)
            and self.broker.workload.active()
        ):
            self.broker.workload.stop()

        if (
            not self.state.runs_balancer
            and self.unit.is_leader()
            and self.balancer.workload.active()
        ):
            self.balancer.workload.stop()

    def _restart_broker(self, event: EventBase) -> None:
        """Handler for `rolling_ops` restart events.

        The RollingOpsManager expecting a charm instance, we cannot move this method to the broker logic.
        """
        # only attempt restart if service is already active
        if not self.broker.healthy:
            event.defer()
            return

        self.broker.workload.restart()

        # FIXME: This logic should be improved as part of ticket DPE-3155
        # For more information, please refer to https://warthogs.atlassian.net/browse/DPE-3155
        time.sleep(10.0)
        self.broker.update_credentials_cache()

    def _disable_enable_restart_broker(self, event: RunWithLock) -> None:
        """Handler for `rolling_ops` disable_enable restart events.

        The RollingOpsManager expecting a charm instance, we cannot move this method to the broker logic.
        """
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

    def _on_collect_status(self, event: CollectStatusEvent):
        for status in self.pending_inactive_statuses + [Status.ACTIVE]:
            event.add_status(status.value.status)


if __name__ == "__main__":
    ops.main(KafkaCharm)  # pyright: ignore[reportCallIssue]
