#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed Machine Operator for Apache Kafka."""

import logging
import time

from charms.data_platform_libs.v0.data_models import TypedCharmBase
from charms.grafana_agent.v0.cos_agent import COSAgentProvider
from charms.operator_libs_linux.v0 import sysctl
from charms.operator_libs_linux.v1.snap import SnapError
from charms.rolling_ops.v0.rollingops import RollingOpsManager, RunWithLock
from ops.charm import StorageAttachedEvent, StorageDetachingEvent, StorageEvent
from ops.framework import EventBase
from ops.main import main
from ops.model import ActiveStatus, StatusBase

from core.cluster import ClusterState
from core.structured_config import CharmConfig
from events.password_actions import PasswordActionEvents
from events.provider import KafkaProvider
from events.tls import TLSHandler
from events.upgrade import KafkaDependencyModel, KafkaUpgrade
from events.zookeeper import ZooKeeperHandler
from health import KafkaHealth
from literals import (
    CHARM_KEY,
    DEPENDENCIES,
    GROUP,
    JMX_EXPORTER_PORT,
    LOGS_RULES_DIR,
    METRICS_RULES_DIR,
    OS_REQUIREMENTS,
    PEER,
    REL_NAME,
    USER,
    DebugLevel,
    Status,
    Substrate,
)
from managers.auth import AuthManager
from managers.config import KafkaConfigManager
from managers.tls import TLSManager
from workload import KafkaWorkload

logger = logging.getLogger(__name__)


class KafkaCharm(TypedCharmBase[CharmConfig]):
    """Charmed Operator for Kafka."""

    config_type = CharmConfig

    def __init__(self, *args):
        super().__init__(*args)
        self.name = CHARM_KEY
        self.substrate: Substrate = "vm"
        self.workload = KafkaWorkload()
        self.state = ClusterState(self, substrate=self.substrate)

        self.health = KafkaHealth(self)

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

        self.config_manager = KafkaConfigManager(
            state=self.state,
            workload=self.workload,
            config=self.config,
            current_version=self.upgrade.current_version,
        )
        self.tls_manager = TLSManager(
            state=self.state, workload=self.workload, substrate=self.substrate
        )
        self.auth_manager = AuthManager(
            state=self.state, workload=self.workload, kafka_opts=self.config_manager.kafka_opts
        )

        # LIB HANDLERS

        self.sysctl_config = sysctl.Config(name=CHARM_KEY)
        self.restart = RollingOpsManager(self, relation="restart", callback=self._restart)
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

        self.framework.observe(getattr(self.on, "install"), self._on_install)
        self.framework.observe(getattr(self.on, "start"), self._on_start)
        self.framework.observe(getattr(self.on, "config_changed"), self._on_config_changed)
        self.framework.observe(getattr(self.on, "update_status"), self._on_update_status)
        self.framework.observe(getattr(self.on, "remove"), self._on_remove)

        self.framework.observe(self.on[PEER].relation_changed, self._on_config_changed)

        self.framework.observe(
            getattr(self.on, "data_storage_attached"), self._on_storage_attached
        )
        self.framework.observe(
            getattr(self.on, "data_storage_detaching"), self._on_storage_detaching
        )

    def _on_install(self, _) -> None:
        """Handler for `install` event."""
        if self.workload.install():
            self._set_os_config()
            self.config_manager.set_environment()
        else:
            self._set_status(Status.SNAP_NOT_INSTALLED)

    def _on_start(self, event: EventBase) -> None:
        """Handler for `start` event."""
        self._set_status(self.state.ready_to_start)
        if not isinstance(self.unit.status, ActiveStatus):
            event.defer()
            return

        # required settings given zookeeper connection config has been created
        self.config_manager.set_zk_jaas_config()
        self.config_manager.set_server_properties()
        self.config_manager.set_client_properties()

        # start kafka service
        self.workload.start()
        logger.info("Kafka snap started")

        # check for connection
        self._on_update_status(event)

        # only log once on successful 'on-start' run
        if isinstance(self.unit.status, ActiveStatus):
            logger.info(f'Broker {self.unit.name.split("/")[1]} connected')

    def _on_config_changed(self, event: EventBase) -> None:
        """Generic handler for most `config_changed` events across relations."""
        # only overwrite properties if service is already active
        if not self.healthy or not self.upgrade.idle:
            event.defer()
            return

        # Load current properties set in the charm workload
        properties = self.workload.read(self.workload.paths.server_properties)
        properties_changed = set(properties) ^ set(self.config_manager.server_properties)

        zk_jaas = self.workload.read(self.workload.paths.zk_jaas)
        zk_jaas_changed = set(zk_jaas) ^ set(self.config_manager.zk_jaas_config.splitlines())

        if not properties or not zk_jaas:
            # Event fired before charm has properly started
            event.defer()
            return

        # update environment
        self.config_manager.set_environment()

        if zk_jaas_changed:
            clean_broker_jaas = [conf.strip() for conf in zk_jaas]
            clean_config_jaas = [
                conf.strip() for conf in self.config_manager.zk_jaas_config.splitlines()
            ]
            logger.info(
                (
                    f'Broker {self.unit.name.split("/")[1]} updating JAAS config - '
                    f"OLD JAAS = {set(clean_broker_jaas) - set(clean_config_jaas)}, "
                    f"NEW JAAS = {set(clean_config_jaas) - set(clean_broker_jaas)}"
                )
            )
            self.config_manager.set_zk_jaas_config()

        if properties_changed:
            logger.info(
                (
                    f'Broker {self.unit.name.split("/")[1]} updating config - '
                    f"OLD PROPERTIES = {set(properties) - set(self.config_manager.server_properties)}, "
                    f"NEW PROPERTIES = {set(self.config_manager.server_properties) - set(properties)}"
                )
            )
            self.config_manager.set_server_properties()

        if zk_jaas_changed or properties_changed:
            if isinstance(event, StorageEvent):  # to get new storages
                self.on[f"{self.restart.name}"].acquire_lock.emit(
                    callback_override="_disable_enable_restart"
                )
            else:
                logger.info("Acquiring lock from _on_config_changed...")
                self.on[f"{self.restart.name}"].acquire_lock.emit()

        # update client_properties whenever possible
        self.config_manager.set_client_properties()

        # If Kafka is related to client charms, update their information.
        if self.model.relations.get(REL_NAME, None) and self.unit.is_leader():
            self.provider.update_connection_info()

    def _on_update_status(self, event: EventBase) -> None:
        """Handler for `update-status` events."""
        if not self.healthy or not self.upgrade.idle:
            return

        if not self.state.zookeeper.broker_active():
            self._set_status(Status.ZK_NOT_CONNECTED)
            return

        # NOTE for situations like IP change and late integration with rack-awareness charm.
        # If properties have changed, the broker will restart.
        self._on_config_changed(event)

        try:
            if not self.health.machine_configured():
                self._set_status(Status.SYSCONF_NOT_OPTIMAL)
                return
        except SnapError as e:
            logger.debug(f"Error: {e}")
            self._set_status(Status.SNAP_NOT_RUNNING)
            return

        self._set_status(Status.ACTIVE)

    def _on_remove(self, _) -> None:
        """Handler for stop."""
        self.sysctl_config.remove()

    def _on_storage_attached(self, event: StorageAttachedEvent) -> None:
        """Handler for `storage_attached` events."""
        # new dirs won't be used until topic partitions are assigned to it
        # either automatically for new topics, or manually for existing
        # set status only for running services, not on startup
        if self.workload.active():
            self._set_status(Status.ADDED_STORAGE)
            self.workload.exec(f"chown -R {USER}:{GROUP} {self.workload.paths.data_path}")
            self.workload.exec(f"chmod -R 770 {self.workload.paths.data_path}")
            self._on_config_changed(event)

    def _on_storage_detaching(self, event: StorageDetachingEvent) -> None:
        """Handler for `storage_detaching` events."""
        # in the case where there may be replication recovery may be possible
        if self.state.brokers and len(self.state.brokers) > 1:
            self._set_status(Status.REMOVED_STORAGE)
        else:
            self._set_status(Status.REMOVED_STORAGE_NO_REPL)

        self._on_config_changed(event)

    def _restart(self, event: EventBase) -> None:
        """Handler for `rolling_ops` restart events."""
        # only attempt restart if service is already active
        if not self.healthy:
            event.defer()
            return

        self.workload.restart()

        # FIXME: This logic should be improved as part of ticket DPE-3155
        # For more information, please refer to https://warthogs.atlassian.net/browse/DPE-3155
        time.sleep(10.0)

        if self.workload.active():
            logger.info(f'Broker {self.unit.name.split("/")[1]} restarted')
        else:
            logger.error(f"Broker {self.unit.name.split('/')[1]} failed to restart")

    def _disable_enable_restart(self, event: RunWithLock) -> None:
        """Handler for `rolling_ops` disable_enable restart events."""
        if not self.healthy:
            logger.warning(f"Broker {self.unit.name.split('/')[1]} is not ready restart")
            event.defer()
            return

        self.workload.disable_enable()
        self.workload.start()

        if self.workload.active():
            logger.info(f'Broker {self.unit.name.split("/")[1]} restarted')
        else:
            logger.error(f"Broker {self.unit.name.split('/')[1]} failed to restart")
            return

    def _set_os_config(self) -> None:
        """Sets sysctl config."""
        try:
            self.sysctl_config.configure(OS_REQUIREMENTS)
        except (sysctl.ApplyError, sysctl.ValidationError, sysctl.CommandError) as e:
            logger.error(f"Error setting values on sysctl: {e.message}")
            self._set_status(Status.SYSCONF_NOT_POSSIBLE)

    @property
    def healthy(self) -> bool:
        """Checks and updates various charm lifecycle states.

        Is slow to fail due to retries, to be used sparingly.

        Returns:
            True if service is alive and active. Otherwise False
        """
        self._set_status(self.state.ready_to_start)
        if not isinstance(self.unit.status, ActiveStatus):
            return False

        if not self.workload.active():
            self._set_status(Status.SNAP_NOT_RUNNING)
            return False

        return True

    def _set_status(self, key: Status) -> None:
        """Sets charm status."""
        status: StatusBase = key.value.status
        log_level: DebugLevel = key.value.log_level

        getattr(logger, log_level.lower())(status.message)
        self.unit.status = status


if __name__ == "__main__":
    main(KafkaCharm)
