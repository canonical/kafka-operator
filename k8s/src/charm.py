#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed Machine Operator for Apache Kafka."""

import logging

import charm_refresh
from charms.data_platform_libs.v0.data_models import TypedCharmBase
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.rolling_ops.v0.rollingops import RollingOpsManager
from ops import (
    ActiveStatus,
    CollectStatusEvent,
    EventBase,
    StatusBase,
)
from ops.log import JujuLogHandler
from ops.main import main

from core.cluster import ClusterState
from core.structured_config import CharmConfig
from events.balancer import BalancerOperator
from events.broker import BrokerOperator
from events.peer_cluster import PeerClusterEventsHandler
from events.refresh import KubernetesKafkaRefresh
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
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("charms.data_platform_libs.v1.data_interfaces").setLevel(logging.WARNING)


class KafkaCharm(TypedCharmBase[CharmConfig]):
    """Charmed Operator for Kafka K8s."""

    config_type = CharmConfig

    def __init__(self, *args):
        super().__init__(*args)

        # Show logger name (module name) in logs
        root_logger = logging.getLogger()
        for handler in root_logger.handlers:
            if isinstance(handler, JujuLogHandler):
                handler.setFormatter(logging.Formatter("{name}:{message}", style="{"))

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
        self.balancer = BalancerOperator(self, self.workload)

        self.tls = TLSHandler(self)

        try:
            self.refresh = charm_refresh.Kubernetes(
                KubernetesKafkaRefresh(
                    workload_name="Kafka",
                    charm_name="kafka-k8s",
                    oci_resource_name="kafka-image",
                    _charm=self,
                )
            )
        except (charm_refresh.PeerRelationNotReady, charm_refresh.UnitTearingDown):
            self.refresh = None

        # Implement refresh logic if refresh is available
        if self.refresh:
            self._handle_refresh_coordination()

        self.metrics_endpoint = MetricsEndpointProvider(
            self,
            jobs=[
                {"static_configs": [{"targets": [f"*:{JMX_EXPORTER_PORT}", f"*:{JMX_CC_PORT}"]}]}
            ],
            alert_rules_path=METRICS_RULES_DIR,
        )
        self.grafana_dashboards = GrafanaDashboardProvider(self)
        self.loki_push = LogForwarder(
            self,
            alert_rules_path=LOGS_RULES_DIR,
            relation_name="logging",
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

        if not self.workload.health_check(
            host=self.state.unit_broker.internal_address,
            runs_broker=self.state.runs_broker,
            runs_controller=self.state.runs_controller,
        ):
            event.defer()
            return

        self.broker.update_credentials_cache()

        # Force update our trusted certs relation data.
        self.broker.update_peer_truststore_state(force=True)

    def _set_status(self, key: Status) -> None:
        """Sets charm status."""
        status: StatusBase = key.value.status
        log_level: DebugLevel = key.value.log_level

        getattr(logger, log_level.lower())(status.message)
        # self.unit.status = status
        self.pending_inactive_statuses.append(key)

    def _on_collect_status(self, event: CollectStatusEvent):
        status = self._determine_unit_status()
        if isinstance(status, list):
            for s in status:
                event.add_status(s.value.status)
        else:
            event.add_status(status)

    def _determine_unit_status(self) -> StatusBase | list[Status]:
        """Determine the unit status, respecting refresh higher priority statuses."""
        if self.refresh and self.refresh.unit_status_higher_priority:
            return self.refresh.unit_status_higher_priority

        # Scaling warning if auto-balance is set.
        # Since this runs on every hook, we intentionally use and for
        # less complex checks first and avoid using all
        if (
            self.state.runs_broker
            and self.state.runs_balancer
            and self.broker.kraft.controller_manager.departing_brokers
        ):
            return Status.SCALING_WARNING.value.status

        # Check for pending inactive statuses (charm-specific logic)
        # Remove active status if present, will be added as default at the end
        charm_statuses_to_check = [
            s
            for s in self.pending_inactive_statuses + [self.state.ready_to_start]
            if s != Status.ACTIVE
        ]
        if charm_statuses_to_check:
            return charm_statuses_to_check

        # Lower priority status from refresh
        if self.refresh and (
            refresh_status := self.refresh.unit_status_lower_priority(
                workload_is_running=self.workload.active()
            )
        ):
            return refresh_status

        # Default to active if no other status is set
        return ActiveStatus()

    def _handle_refresh_coordination(self) -> None:
        """Handle workload-allowed-to-start and next-unit-allowed-to-refresh hooks."""
        if not self.refresh or not self.workload.container_can_connect:
            return

        # Only proceed with coordination if workload is allowed to start
        if not self.refresh.in_progress or not self.refresh.workload_allowed_to_start:
            return

        # Handle next-unit-allowed-to-refresh logic
        if not self.refresh.next_unit_allowed_to_refresh:
            # required settings given zookeeper connection config has been created
            self.broker.config_manager.set_environment()
            self.broker.config_manager.set_server_properties()
            self.broker.config_manager.set_client_properties()
            self.broker.tls_manager.configure()

            # start kafka service
            self.broker.workload.start()

            # Check if workload is ready and healthy before allowing next unit to refresh
            if self._is_workload_healthy():
                self.refresh.next_unit_allowed_to_refresh = True
                logger.info("Unit is healthy, allowing next unit to refresh")
            else:
                logger.debug("Unit not yet healthy, delaying next unit refresh")

    def _is_workload_healthy(self) -> bool:
        """Check if the workload is healthy and ready for next unit to refresh.

        Returns:
            True if all relevant workloads are healthy and active, False otherwise.
        """
        # Check if workload is active first
        if not self.workload.active():
            return False

        # For broker role, check broker health
        if self.state.runs_broker or self.state.runs_controller:
            if not self.broker.healthy:
                return False

        return True

    @property
    def refresh_not_ready(self) -> bool:
        """Check if refresh is not available or currently in progress."""
        return not self.refresh or self.refresh.in_progress


if __name__ == "__main__":
    main(KafkaCharm)
