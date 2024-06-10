#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed Machine Operator for Apache Kafka."""

import logging

from charms.data_platform_libs.v0.data_models import TypedCharmBase
from charms.grafana_agent.v0.cos_agent import COSAgentProvider
from charms.operator_libs_linux.v0 import sysctl
from charms.rolling_ops.v0.rollingops import RollingOpsManager
from ops.main import main
from ops.model import StatusBase

from core.cluster import ClusterState
from core.models import Substrates
from core.structured_config import CharmConfig
from events.broker import BrokerEvents
from events.optimizer import OptimizerEvents
from events.password_actions import PasswordActionEvents
from events.provider import KafkaProvider
from events.tls import TLSHandler
from events.upgrade import KafkaDependencyModel, KafkaUpgrade
from events.zookeeper import ZooKeeperHandler
from health import KafkaHealth
from literals import (
    BROKER,
    CHARM_KEY,
    DEPENDENCIES,
    JMX_EXPORTER_PORT,
    LOGS_RULES_DIR,
    METRICS_RULES_DIR,
    OPTIMIZER,
    SUBSTRATE,
    DebugLevel,
    Status,
)
from managers.auth import AuthManager
from managers.config import ConfigManager
from managers.tls import TLSManager
from workload import KafkaWorkload

logger = logging.getLogger(__name__)


class KafkaCharm(TypedCharmBase[CharmConfig]):
    """Charmed Operator for Kafka."""

    config_type = CharmConfig

    def __init__(self, *args):
        super().__init__(*args)
        self.name = CHARM_KEY
        self.substrate: Substrates = SUBSTRATE
        self.role = BROKER if self.config.role == "broker" else OPTIMIZER

        # Common attrs init
        self.workload = KafkaWorkload(self.role)
        self.state = ClusterState(self, substrate=self.substrate)
        self.health = KafkaHealth(self)

        self.broker_events = BrokerEvents(self)
        self.optimizer_events = OptimizerEvents(self)

        if self.role == OPTIMIZER:
            self.config_manager = ConfigManager(
                self.role,
                state=self.state,
                workload=self.workload,
                config=self.config,
            )
            return

        self._init_broker()

    def _init_broker(self) -> None:
        """Init broker specific attributes."""
        # HANDLERS

        self.password_action_events = PasswordActionEvents(self)
        self.zookeeper = ZooKeeperHandler(self)
        self.tls = TLSHandler(self)
        self.provider = KafkaProvider(self)
        self.upgrade = KafkaUpgrade(
            self,
            dependency_model=KafkaDependencyModel(
                **DEPENDENCIES  # pyright: ignore[reportGeneralTypeIssues, reportArgumentType]
            ),
        )

        # MANAGERS

        self.config_manager = ConfigManager(
            self.role,
            state=self.state,
            workload=self.workload,
            config=self.config,
            current_version=self.upgrade.current_version,
        )
        self.tls_manager = TLSManager(
            state=self.state, workload=self.workload, substrate=self.substrate
        )
        self.auth_manager = AuthManager(
            state=self.state,
            workload=self.workload,
            kafka_opts=self.config_manager.kafka_opts,
            log4j_opts=self.config_manager.tools_log4j_opts,
        )

        # LIB HANDLERS

        self.sysctl_config = sysctl.Config(name=CHARM_KEY)
        self.restart = RollingOpsManager(
            self, relation="restart", callback=self.broker_events._restart
        )
        self._grafana_agent = COSAgentProvider(
            self,
            metrics_endpoints=[
                # Endpoint for the kafka and jmx exporters
                # See https://github.com/canonical/charmed-kafka-snap for details
                {"path": "/metrics", "port": JMX_EXPORTER_PORT},
            ],
            metrics_rules_dir=METRICS_RULES_DIR,
            logs_rules_dir=LOGS_RULES_DIR,
            log_slots=[f"{self.workload.SNAP_NAME}:{self.workload.LOG_SLOT}"],
        )

    def _set_status(self, key: Status) -> None:
        """Sets charm status."""
        status: StatusBase = key.value.status
        log_level: DebugLevel = key.value.log_level

        getattr(logger, log_level.lower())(status.message)
        self.unit.status = status


if __name__ == "__main__":
    main(KafkaCharm)
