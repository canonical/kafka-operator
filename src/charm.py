#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed Machine Operator for Apache Kafka."""

import logging

from charms.data_platform_libs.v0.data_models import TypedCharmBase
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v0.loki_push_api import LogProxyConsumer
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.rolling_ops.v0.rollingops import RollingOpsManager
from ops import (
    CollectStatusEvent,
    EventBase,
    StatusBase,
)
from ops.main import main

from core.cluster import ClusterState
from core.structured_config import CharmConfig
from events.balancer import BalancerOperator
from events.broker import BrokerOperator
from events.peer_cluster import PeerClusterEventsHandler
from events.tls import TLSHandler
from literals import (
    CHARM_KEY,
    CONTAINER,
    JMX_CC_PORT,
    JMX_EXPORTER_PORT,
    LOGS_RULES_DIR,
    METRICS_RULES_DIR,
    SUBSTRATE,
    DebugLevel,
    Status,
    Substrates,
)
from workload import KafkaWorkload

logger = logging.getLogger(__name__)


class KafkaCharm(TypedCharmBase[CharmConfig]):
    """Charmed Operator for Kafka K8s."""

    config_type = CharmConfig

    def __init__(self, *args):
        super().__init__(*args)
        self.name = CHARM_KEY
        self.substrate: Substrates = SUBSTRATE
        self.pending_inactive_statuses: list[Status] = []

        # Common attrs init
        self.state = ClusterState(self, substrate=self.substrate)

        self.workload = KafkaWorkload(
            container=self.unit.get_container(CONTAINER)
        )  # Will be re-instantiated for each role.

        self.restart = RollingOpsManager(self, relation="restart", callback=self._restart_broker)

        self.framework.observe(getattr(self.on, "config_changed"), self._on_roles_changed)
        self.framework.observe(self.on.collect_unit_status, self._on_collect_status)
        self.framework.observe(self.on.collect_app_status, self._on_collect_status)

        # peer-cluster events are shared between all roles, so necessary to init here to avoid instantiating multiple times
        self.peer_cluster = PeerClusterEventsHandler(self)

        # Register roles event handlers after global ones, so that they get the priority.
        self.broker = BrokerOperator(self)
        self.balancer = BalancerOperator(self)

        self.tls = TLSHandler(self)

        self.metrics_endpoint = MetricsEndpointProvider(
            self,
            jobs=[
                {"static_configs": [{"targets": [f"*:{JMX_EXPORTER_PORT}", f"*:{JMX_CC_PORT}"]}]}
            ],
            alert_rules_path=METRICS_RULES_DIR,
        )
        self.grafana_dashboards = GrafanaDashboardProvider(self)
        self.loki_push = LogProxyConsumer(
            self,
            log_files=[
                f"{self.broker.workload.paths.logs_path}/server.log",
                f"{self.balancer.workload.paths.logs_path}/kafkacruisecontrol.log",
            ],
            alert_rules_path=LOGS_RULES_DIR,
            relation_name="logging",
            container_name="kafka",
        )

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
        """Handler for `rolling_ops` restart events."""
        # only attempt restart if service is already active
        if not self.broker.healthy:
            event.defer()
            return

        self.broker.workload.restart()

        if self.broker.healthy:
            logger.info(f'Broker {self.unit.name.split("/")[1]} restarted')
        else:
            logger.error(f"Broker {self.unit.name.split('/')[1]} failed to restart")

    def _set_status(self, key: Status) -> None:
        """Sets charm status."""
        status: StatusBase = key.value.status
        log_level: DebugLevel = key.value.log_level

        getattr(logger, log_level.lower())(status.message)
        # self.unit.status = status
        self.pending_inactive_statuses.append(key)

    def _on_collect_status(self, event: CollectStatusEvent):
        for status in self.pending_inactive_statuses + [Status.ACTIVE]:
            event.add_status(status.value.status)


if __name__ == "__main__":
    main(KafkaCharm)
