#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed Machine Operator for Apache Kafka."""

import logging
from typing import Optional

from ops.charm import (
    ActionEvent,
    StorageAttachedEvent,
    StorageDetachingEvent,
    StorageEvent,
)
from ops.framework import EventBase
from ops.main import main
from ops.model import ActiveStatus

from charms.data_platform_libs.v0.data_models import TypedCharmBase
from charms.grafana_agent.v0.cos_agent import COSAgentProvider
from charms.operator_libs_linux.v0 import sysctl
from charms.operator_libs_linux.v1.snap import SnapError
from charms.rolling_ops.v0.rollingops import RollingOpsManager, RunWithLock
from literals import (
    ADMIN_USER,
    CHARM_KEY,
    DEPENDENCIES,
    JMX_EXPORTER_PORT,
    LOGS_RULES_DIR,
    METRICS_RULES_DIR,
    OS_REQUIREMENTS,
    REL_NAME,
    Status,
    CHARMED_KAFKA_SNAP_REVISION
)
from new.common.charm import PeerRelationMixin
from new.common.vm import SnapService
from new.config import ServerConfig
from new.core.workload import CharmedKafkaPath
from new.handlers.parsers import charm_state
from new.handlers.provider import KafkaProvider
from new.handlers.tls import TLSHandlers
from new.handlers.zookeeper import ZookeeperHandlers
from new.vm.workload import KafkaService
from structured_config import CharmConfig
from upgrade import KafkaDependencyModel, KafkaUpgrade
from utils import (
    broker_active,
    generate_password,
    set_snap_mode_bits,
    set_snap_ownership,
)

logger = logging.getLogger(__name__)


class KafkaCharm(TypedCharmBase[CharmConfig], PeerRelationMixin):
    """Charmed Operator for Kafka."""

    config_type = CharmConfig

    def __init__(self, *args):
        super().__init__(*args)

        # Parsing the charm state
        self.state = charm_state(self)

        # Setting for the workload
        paths: CharmedKafkaPath[str] = CharmedKafkaPath(
            conf_path="/var/snap/charmed-kafka/current/etc/kafka",
            binaries_path="/snap/charmed-kafka/current/opt/kafka",
            mapper=lambda x: x  # IDENTITY
        )
        snap = SnapService(
            name="charmed-kafka", component="kafka", service="daemon",
            revision=CHARMED_KAFKA_SNAP_REVISION, log_slot="logs", plugs=["removable-media"]
        )
        self.workload = KafkaService(self.state, snap, paths)

        self.sysctl_config = sysctl.Config(name=CHARM_KEY)

        self.restart = RollingOpsManager(self, relation="restart", callback=self._restart)

        self.upgrade = KafkaUpgrade(
            self,
            dependency_model=KafkaDependencyModel(
                **DEPENDENCIES  # pyright: ignore[reportGeneralTypeIssues]
            ),
        )

        self.server_config = ServerConfig(
            self.state.config, paths, self.state.cluster, self.state.upgrade,
            self.state.zookeeper, self.state.clients
        )

        ############################################################################
        #  CHARM HANDLERS
        ############################################################################
        self.tls = TLSHandlers(self, self.state, self.workload)
        self.zookeeper = ZookeeperHandlers(self, self.state, self.workload)
        self.clients = KafkaProvider(self, self.state, self.workload, self._on_config_changed)
        ############################################################################

        self.framework.observe(getattr(self.on, "start"), self._on_start)
        self.framework.observe(getattr(self.on, "install"), self._on_install)
        self.framework.observe(getattr(self.on, "config_changed"), self._on_config_changed)
        self.framework.observe(getattr(self.on, "update_status"), self._on_update_status)
        self.framework.observe(getattr(self.on, "remove"), self._on_remove)

        self.framework.observe(getattr(self.on, "set_password_action"), self._set_password_action)
        self.framework.observe(
            getattr(self.on, "get_admin_credentials_action"), self._get_admin_credentials_action
        )

        self.framework.observe(
            getattr(self.on, "data_storage_attached"), self._on_storage_attached
        )
        self.framework.observe(
            getattr(self.on, "data_storage_detaching"), self._on_storage_detaching
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
            log_slots=[f"{snap.name}:{snap.log_slot}"],
        )

    def _on_remove(self, _) -> None:
        """Handler for stop."""
        self.sysctl_config.remove()

    def _on_update_status(self, event: EventBase) -> None:
        """Handler for `update-status` events."""
        if not self.workload.health() or not self.upgrade.idle:
            return

        if not broker_active(
                unit=self.unit,
                zookeeper_config=self.state.zookeeper,
        ):
            self.app.status = Status.ZK_NOT_CONNECTED
            return

        # NOTE for situations like IP change and late integration with rack-awareness charm.
        # If properties have changed, the broker will restart.
        self._on_config_changed(event)

        try:
            if not self.health.machine_configured():
                self.app.status = Status.SYSCONF_NOT_OPTIMAL
                return
        except SnapError:
            self.app.status = Status.SNAP_NOT_RUNNING
            return

        self.app.status = Status.ACTIVE

    def _on_storage_attached(self, event: StorageAttachedEvent) -> None:
        """Handler for `storage_attached` events."""
        # new dirs won't be used until topic partitions are assigned to it
        # either automatically for new topics, or manually for existing
        # set status only for running services, not on startup
        if self.snap.active():
            self._set_status(Status.ADDED_STORAGE)
            set_snap_ownership(path=self.snap.DATA_PATH)
            set_snap_mode_bits(path=self.snap.DATA_PATH)
            self._on_config_changed(event)

    def _on_storage_detaching(self, event: StorageDetachingEvent) -> None:
        """Handler for `storage_detaching` events."""
        # in the case where there may be replication recovery may be possible
        if self.state.cluster and len(self.state.cluster.hosts):
            self.app.status = Status.REMOVED_STORAGE
        else:
            self.app.status = Status.REMOVED_STORAGE_NO_REPL

        self._on_config_changed(event)

    def _on_install(self, _) -> None:
        """Handler for `install` event."""
        if self.workload.install():  # SHOULD WE ALSO HAVE AN INSTALL METHOD
            self._set_os_config()

            self.workload.update_environment(self.server_config.environment)

            self.unit.status = Status.ZK_NOT_RELATED
        else:
            self.unit.status = Status.SNAP_NOT_INSTALLED

    def _on_start(self, event: EventBase) -> None:
        """Handler for `start` event."""
        if not self.workload.ready():
            event.defer()
            return

        # required settings given zookeeper connection config has been created
        self.zookeeper.zookeeper.set_zk_jaas_config()

        with self.workload.write.server_properties as fid:
            fid.write(self.server_config.server_properties)

        with self.workload.write.client_properties as fid:
            fid.write(self.server_config.client_properties)

        # start kafka service
        self.workload.start()

        logger.info("Kafka started")

        # check for connection
        self._on_update_status(event)

        # only log once on successful 'on-start' run
        if isinstance(self.unit.status, ActiveStatus):
            logger.info(f'Broker {self.unit.name.split("/")[1]} connected')

    def _on_config_changed(self, event: EventBase) -> None:
        """Generic handler for most `config_changed` events across relations."""
        # only overwrite properties if service is already active
        if not self.workload.health() or not self.upgrade.idle:
            event.defer()
            return

        # Load current properties set in the charm workload
        with self.workload.read.server_properties as fid:
            properties = fid.read().split("\n")

        if not properties:
            # Event fired before charm has properly started
            event.defer()
            return

        if set(properties) ^ set(self.server_config.server_properties):
            logger.info(
                (
                    f'Broker {self.unit.name.split("/")[1]} updating config - '
                    f"OLD PROPERTIES = {set(properties) - set(self.server_config.server_properties)}, "
                    f"NEW PROPERTIES = {set(self.server_config.server_properties) - set(properties)}"
                )
            )

            with self.workload.write.server_properties as fid:
                fid.write(self.server_config.server_properties)

            if isinstance(event, StorageEvent):  # to get new storages
                self.on[f"{self.restart.name}"].acquire_lock.emit(
                    callback_override="_disable_enable_restart"
                )
            else:
                logger.info("Acquiring lock from _on_config_changed...")
                self.on[f"{self.restart.name}"].acquire_lock.emit()

        # update client_properties whenever possible
        with self.workload.write.client_properties as fid:
            fid.write(self.server_config.client_properties)

        # If Kafka is related to client charms, update their information.
        if self.model.relations.get(REL_NAME, None) and self.unit.is_leader():
            self.provider.update_connection_info()  # THIS NEEDS TO BE WRITTEN EXPLICITELY

    def _restart(self, event: EventBase) -> None:
        """Handler for `rolling_ops` restart events."""
        # only attempt restart if service is already active
        if not self.workload.health():
            event.defer()
            return

        self.workload.stop()
        self.workload.start()
        # OR MAYBE IT IS ACTUALLY BETTER TO HAVE A RESTART/REPLAN COMMON METHOD?

        if self.workload.health():
            logger.info(f'Broker {self.state.cluster.unit.unit} restarted')
        else:
            logger.error(f"Broker {self.state.cluster.unit.unit} failed to restart")

    def _disable_enable_restart(self, event: RunWithLock) -> None:
        """Handler for `rolling_ops` disable_enable restart events."""
        if not self.workload.health():
            logger.warning(f"Broker {self.unit.name.split('/')[1]} is not ready restart")
            event.defer()
            return

        self.snap.disable_enable()  # WOULD IT BE POSSIBLE TO MODEL THIS?
        self.snap.start_snap_service()

        if self.workload.health():
            logger.info(f'Broker {self.unit.name.split("/")[1]} restarted')
        else:
            logger.error(f"Broker {self.unit.name.split('/')[1]} failed to restart")
            return

    def _set_password_action(self, event: ActionEvent) -> None:
        """Handler for set-password action.

        Set the password for a specific user, if no passwords are passed, generate them.
        """
        if not self.unit.is_leader():
            msg = "Password rotation must be called on leader unit"
            logger.error(msg)
            event.fail(msg)
            return

        if not self.workload.health():
            event.defer()
            return

        username = event.params["username"]
        new_password = event.params.get("password", generate_password())

        if new_password in self.state.cluster.internal_user_credentials.values():
            msg = "Password already exists, please choose a different password."
            logger.error(msg)
            event.fail(msg)
            return

        try:
            self.zookeeper.zookeeper.update_internal_user(username=username, password=new_password)
        except Exception as e:
            logger.error(str(e))
            event.fail(f"unable to set password for {username}")

        # Store the password on application databag
        self.set_secret(scope="app", key=f"{username}-password", value=new_password)
        event.set_results({f"{username}-password": new_password})

    def _get_admin_credentials_action(self, event: ActionEvent) -> None:
        with self.workload.read.client_properties as fid:
            client_properties = fid.read().split("\n")

        if not client_properties:
            msg = "client.properties file not found on target unit."
            logger.error(msg)
            event.fail(msg)
            return

        admin_properties = set(client_properties) - set(self.server_config.tls_properties)

        event.set_results(
            {
                "username": ADMIN_USER,
                "password": self.state.cluster.internal_user_credentials[ADMIN_USER],
                "client-properties": "\n".join(admin_properties),
            }
        )

    def _set_os_config(self) -> None:
        """Sets sysctl config."""
        try:
            self.sysctl_config.configure(OS_REQUIREMENTS)
        except (sysctl.ApplyError, sysctl.ValidationError, sysctl.CommandError) as e:
            logger.error(f"Error setting values on sysctl: {e.message}")
            self.app.status = Status.SYSCONF_NOT_POSSIBLE

    def get_secret(self, scope: str, key: str) -> Optional[str]:
        """Get TLS secret from the secret storage.

        Args:
            scope: whether this secret is for a `unit` or `app`
            key: the secret key name

        Returns:
            String of key value.
            None if non-existent key
        """
        if scope == "unit":
            return self.unit_peer_data.get(key, None)
        elif scope == "app":
            return self.app_peer_data.get(key, None)
        else:
            raise RuntimeError("Unknown secret scope.")

    def set_secret(self, scope: str, key: str, value: Optional[str]) -> None:
        """Get TLS secret from the secret storage.

        Args:
            scope: whether this secret is for a `unit` or `app`
            key: the secret key name
            value: the value for the secret key
        """
        if scope == "unit":
            if not value:
                self.unit_peer_data.update({key: ""})
                return
            self.unit_peer_data.update({key: value})
        elif scope == "app":
            if not value:
                self.app_peer_data.update({key: ""})
                return
            self.app_peer_data.update({key: value})
        else:
            raise RuntimeError("Unknown secret scope.")


if __name__ == "__main__":
    main(KafkaCharm)
