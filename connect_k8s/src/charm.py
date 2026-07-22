#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed Machine Operator for Apache Kafka Connect."""

import datetime
import logging
import os
from typing import cast

os.environ.update({"SUBSTRATE": "k8s"})

import ops
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v0.loki_push_api import LogProxyConsumer
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.rolling_ops.v0.rollingops import RollingOpsManager
from ops import (
    CollectStatusEvent,
    EventBase,
    InstallEvent,
    ModelError,
    StartEvent,
    StatusBase,
)
from single_kernel_kafka.core.connect_models import ConnectCharmBase
from single_kernel_kafka.core.connect_models import ConnectContext as Context
from single_kernel_kafka.core.literals import (
    CONNECT_DEPENDENCIES,
    SUBSTRATE,
    ConnectLiterals,
    ConnectStatus,
    Substrates,
    TLSScope,
)
from single_kernel_kafka.core.structured_config import ConnectCharmConfig
from single_kernel_kafka.events.connect.base import ConnectHandler
from single_kernel_kafka.events.connect.kafka import KafkaHandler
from single_kernel_kafka.events.connect.tls import TLSHandler
from single_kernel_kafka.events.connect.upgrade import ConnectDependencyModel, ConnectUpgradeK8s
from single_kernel_kafka.events.connect.user_secrets import SecretsHandler
from single_kernel_kafka.managers.auth import ConnectAuthManager
from single_kernel_kafka.managers.connect import ConnectManager
from single_kernel_kafka.managers.connect_config import ConfigManager
from single_kernel_kafka.managers.tls import ConnectSansBuilder, TLSManager
from single_kernel_kafka.workload import ConnectWorkloadK8s

logger = logging.getLogger(__name__)


class ConnectCharm(ConnectCharmBase):
    """Charmed Operator for Apache Kafka Connect."""

    config_type = ConnectCharmConfig

    def __init__(self, *args):
        super().__init__(*args)
        self.name = "kafka-connect-k8s"
        self.substrate: Substrates = cast(Substrates, SUBSTRATE)
        self.pending_inactive_statuses: list[ConnectStatus] = []

        self.workload = ConnectWorkloadK8s(container=self.unit.get_container(self.container_name))
        self.context = Context(self, substrate=self.substrate)
        self.auth_manager = ConnectAuthManager(
            context=self.context,
            workload=self.workload,
            store_path=self.workload.connect_paths.passwords,
        )
        self.config_manager = ConfigManager(
            context=self.context, workload=self.workload, config=self.config
        )
        self.connect_manager = ConnectManager(context=self.context, workload=self.workload)
        self.sans_builder = ConnectSansBuilder(self.context, self.workload, self.substrate)
        self.tls_manager = TLSManager(
            settings=self.context.tls_manager_settings,
            workload=self.workload,
            substrate=self.substrate,
            sans_builder=self.sans_builder,
            conf_path=self.workload.connect_paths.config_dir,
        )

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.remove, self._on_remove)
        self.framework.observe(self.on.collect_unit_status, self._on_collect_status)
        self.framework.observe(self.on.collect_app_status, self._on_collect_status)

        if self.substrate == "k8s":
            self.framework.observe(getattr(self.on, "kafka_connect_pebble_ready"), self._on_start)

        self.connect = ConnectHandler(self)
        self.kafka = KafkaHandler(self)
        self.tls = TLSHandler(self)
        self.upgrade = ConnectUpgradeK8s(
            self,
            substrate=self.substrate,
            dependency_model=ConnectDependencyModel(
                **CONNECT_DEPENDENCIES  # pyright: ignore[reportArgumentType]
            ),
        )

        self.user_secrets = SecretsHandler(self)

        self.restart = RollingOpsManager(self, relation="restart", callback=self._restart_callback)

        self.metrics_endpoint = MetricsEndpointProvider(
            self,
            jobs=[
                {
                    "static_configs": [
                        {
                            "targets": [
                                f"*:{ConnectLiterals.JMX_EXPORTER_PORT}",
                            ]
                        }
                    ]
                }
            ],
            alert_rules_path=ConnectLiterals.METRICS_RULES_DIR,
        )
        self.grafana_dashboards = GrafanaDashboardProvider(self)
        self.loki_push = LogProxyConsumer(
            self,
            log_files=[
                f"{self.workload.connect_paths.logs_dir}/connect.log",
            ],
            relation_name="logging",
            container_name=self.container_name,
        )

    def _on_install(self, event: InstallEvent) -> None:
        """Handler for `install` event."""
        if not self.workload.container_can_connect:
            event.defer()
            return

    def _on_start(self, event: StartEvent) -> None:
        if not self.workload.container_can_connect:
            event.defer()
            return

        if not self.context.kafka_client.relation:
            self._set_status(ConnectStatus.MISSING_KAFKA)

    def _on_remove(self, _) -> None:
        """Handler for `stop` event."""
        self.workload.stop()

    def _set_status(self, key: ConnectStatus) -> None:
        """Sets charm status."""
        status: StatusBase = key.value.status
        log_level = key.value.log_level

        getattr(logger, log_level.lower())(status.message)
        self.pending_inactive_statuses.append(key)

    def _on_collect_status(self, event: CollectStatusEvent):
        """Handler for `collect-status` event."""
        workload_status = (
            ConnectStatus.INSTALLING if not self.workload.installed else self.context.status
        )
        for status in self.pending_inactive_statuses + [workload_status]:
            event.add_status(status.value.status)

    def _restart_callback(self, event: EventBase) -> None:
        """Handler for `rolling_ops` restart events."""
        if not self.context.ready or not self.context.worker_unit.should_restart:
            return

        self.connect_manager.restart_worker()

        for _ in range(4):
            # shouldn't take longer than a minute
            if self.connect_manager.healthy:
                self.context.worker_unit.should_restart = False
                return

    def reconcile(self) -> None:
        """Substrate-agnostic method for startup/restarts/config-changes which orchestrates workload, managers and handlers.

        This method is safe to call and only triggers a workload restart if necessary.
        """
        if not self.connect_manager.plugin_path_initiated:
            self.connect_manager.init_plugin_path()

        try:
            resource_path = self.model.resources.fetch(ConnectLiterals.PLUGIN_RESOURCE_KEY)
            self.connect_manager.load_plugin(resource_path)
        except RuntimeError:
            logger.error(
                f"Resource {ConnectLiterals.PLUGIN_RESOURCE_KEY} not defined in the charm build."
            )
        except (NameError, ModelError):
            logger.debug(
                f"Resource {ConnectLiterals.PLUGIN_RESOURCE_KEY} not found or could not be downloaded, skipping plugin loading."
            )

        self.connect.update_plugins()
        self.connect.update_clients_data()

        # Check if SANs have changed.
        if all(
            [
                self.context.peer_workers.tls_enabled,
                self.context.worker_unit.tls.certificate,
                self.context.worker_unit.tls.ca,
                self.context.worker_unit.tls.private_key,
            ]
        ):
            if self.tls_manager.sans_changed(TLSScope.CONNECT):
                unit_tls_context = self.context.worker_unit.tls
                self.tls.certificates.on.certificate_expiring.emit(
                    certificate=unit_tls_context.certificate,
                    expiry=datetime.datetime.now().isoformat(),
                )
                self.context.worker_unit.update(
                    {unit_tls_context.CERT: ""}
                )  # ensures only single requested new certs, will be replaced on new certificate-available event

                return  # config-changed would be eventually fired on certificate-available, so no need to defer.

        current_config = set(self.workload.read(self.workload.connect_paths.worker_properties))
        diff = set(self.config_manager.properties) ^ current_config

        if diff:
            self.context.worker_unit.should_restart = True

        if not self.context.worker_unit.should_restart:
            return

        if not self.context.ready:
            self._set_status(self.context.status)
            return

        self.connect.enable_auth()
        self.tls_manager.configure()
        self.config_manager.configure()

        self.on[f"{self.restart.name}"].acquire_lock.emit()


if __name__ == "__main__":
    ops.main(ConnectCharm)  # pyright: ignore[reportCallIssue]
