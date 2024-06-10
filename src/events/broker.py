"""Define broker events."""

import logging
from time import time
from typing import TYPE_CHECKING

from charms.operator_libs_linux.v0 import sysctl
from charms.operator_libs_linux.v1.snap import SnapError
from charms.rolling_ops.v0.rollingops import RunWithLock
from ops import (
    ActiveStatus,
    EventBase,
    Object,
    SecretChangedEvent,
    StorageAttachedEvent,
    StorageDetachingEvent,
    StorageEvent,
)

from literals import BROKER, GROUP, OS_REQUIREMENTS, PEER, REL_NAME, USER, Status

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)

BROKER_EVENTS = "optimizer-events"


class BrokerEvents(Object):
    """Implement broker specific events."""

    def __init__(self, charm) -> None:
        super().__init__(charm, BROKER_EVENTS)
        self.charm: "KafkaCharm" = charm

        if self.charm.role != BROKER:
            return

        self.framework.observe(getattr(self.charm.on, "install"), self._on_install)
        self.framework.observe(getattr(self.charm.on, "start"), self._on_start)
        self.framework.observe(getattr(self.charm.on, "config_changed"), self._on_config_changed)
        self.framework.observe(getattr(self.charm.on, "update_status"), self._on_update_status)
        self.framework.observe(getattr(self.charm.on, "remove"), self._on_remove)
        self.framework.observe(getattr(self.charm.on, "secret_changed"), self._on_secret_changed)

        self.framework.observe(self.charm.on[PEER].relation_changed, self._on_config_changed)

        self.framework.observe(
            getattr(self.charm.on, "data_storage_attached"), self._on_storage_attached
        )
        self.framework.observe(
            getattr(self.charm.on, "data_storage_detaching"), self._on_storage_detaching
        )

    def _on_install(self, _) -> None:
        """Handler for `install` event."""
        if not self.charm.workload.install():
            self.charm._set_status(Status.SNAP_NOT_INSTALLED)
            return

        self._set_os_config()
        self.charm.config_manager.set_environment()
        self.charm.unit.set_workload_version(self.charm.workload.get_version())

    def _on_start(self, event: EventBase) -> None:
        """Handler for `start` event."""
        self.charm._set_status(self.charm.state.ready_to_start)
        if not isinstance(self.charm.unit.status, ActiveStatus):
            event.defer()
            return

        # required settings given zookeeper connection config has been created
        self.charm.config_manager.set_zk_jaas_config()
        self.charm.config_manager.set_server_properties()
        self.charm.config_manager.set_client_properties()

        # start kafka service
        self.charm.workload.start()
        logger.info("Kafka snap started")

        # check for connection
        self._on_update_status(event)

        # only log once on successful 'on-start' run
        if isinstance(self.charm.unit.status, ActiveStatus):
            logger.info(f'Broker {self.charm.unit.name.split("/")[1]} connected')

    def _on_config_changed(self, event: EventBase) -> None:
        """Generic handler for most `config_changed` events across relations."""
        # only overwrite properties if service is already active
        if not self.healthy or not self.charm.upgrade.idle:
            event.defer()
            return

        # Load current properties set in the charm workload
        properties = self.charm.workload.read(self.charm.workload.paths.server_properties)
        properties_changed = set(properties) ^ set(self.charm.config_manager.server_properties)

        zk_jaas = self.charm.workload.read(self.charm.workload.paths.zk_jaas)
        zk_jaas_changed = set(zk_jaas) ^ set(self.charm.config_manager.zk_jaas_config.splitlines())

        if not properties or not zk_jaas:
            # Event fired before charm has properly started
            event.defer()
            return

        # update environment
        self.charm.config_manager.set_environment()
        self.charm.unit.set_workload_version(self.charm.workload.get_version())

        if zk_jaas_changed:
            clean_broker_jaas = [conf.strip() for conf in zk_jaas]
            clean_config_jaas = [
                conf.strip() for conf in self.charm.config_manager.zk_jaas_config.splitlines()
            ]
            logger.info(
                (
                    f'Broker {self.charm.unit.name.split("/")[1]} updating JAAS config - '
                    f"OLD JAAS = {set(clean_broker_jaas) - set(clean_config_jaas)}, "
                    f"NEW JAAS = {set(clean_config_jaas) - set(clean_broker_jaas)}"
                )
            )
            self.charm.config_manager.set_zk_jaas_config()

        if properties_changed:
            logger.info(
                (
                    f'Broker {self.charm.unit.name.split("/")[1]} updating config - '
                    f"OLD PROPERTIES = {set(properties) - set(self.charm.config_manager.server_properties)}, "
                    f"NEW PROPERTIES = {set(self.charm.config_manager.server_properties) - set(properties)}"
                )
            )
            self.charm.config_manager.set_server_properties()

        if zk_jaas_changed or properties_changed:
            if isinstance(event, StorageEvent):  # to get new storages
                self.on[f"{self.charm.restart.name}"].acquire_lock.emit(
                    callback_override="_disable_enable_restart"
                )
            else:
                self.on[f"{self.charm.restart.name}"].acquire_lock.emit()

        # update client_properties whenever possible
        self.charm.config_manager.set_client_properties()

        # If Kafka is related to client charms, update their information.
        if self.model.relations.get(REL_NAME, None) and self.charm.unit.is_leader():
            self.update_client_data()

    def _on_update_status(self, _: EventBase) -> None:
        """Handler for `update-status` events."""
        if not self.healthy or not self.charm.upgrade.idle:
            return

        if not self.charm.state.zookeeper.broker_active():
            self.charm._set_status(Status.ZK_NOT_CONNECTED)
            return

        # NOTE for situations like IP change and late integration with rack-awareness charm.
        # If properties have changed, the broker will restart.
        self.on.config_changed.emit()

        try:
            if not self.charm.health.machine_configured():
                self.charm._set_status(Status.SYSCONF_NOT_OPTIMAL)
                return
        except SnapError as e:
            logger.debug(f"Error: {e}")
            self.charm._set_status(Status.SNAP_NOT_RUNNING)
            return

        self.charm._set_status(Status.ACTIVE)

    def _on_remove(self, _) -> None:
        """Handler for stop."""
        self.charm.sysctl_config.remove()

    def _on_secret_changed(self, event: SecretChangedEvent) -> None:
        """Handler for `secret_changed` events."""
        if not event.secret.label or not self.charm.state.cluster.relation:
            return

        if event.secret.label == self.charm.state.cluster.data_interface._generate_secret_label(
            PEER,
            self.charm.state.cluster.relation.id,
            "extra",  # pyright: ignore[reportArgumentType] -- Changes with the https://github.com/canonical/data-platform-libs/issues/124
        ):
            self.on.config_changed.emit()

    def _on_storage_attached(self, event: StorageAttachedEvent) -> None:
        """Handler for `storage_attached` events."""
        # new dirs won't be used until topic partitions are assigned to it
        # either automatically for new topics, or manually for existing
        # set status only for running services, not on startup
        self.charm.workload.exec(f"chmod -R 750 {self.charm.workload.paths.data_path}")
        self.charm.workload.exec(f"chown -R {USER}:{GROUP} {self.charm.workload.paths.data_path}")
        self.charm.workload.exec(
            f"""find {self.charm.workload.paths.data_path} -type f -name "meta.properties" -delete || true"""
        )
        if self.charm.workload.active():
            self.charm._set_status(Status.ADDED_STORAGE)
            self._on_config_changed(event)

    def _on_storage_detaching(self, _: StorageDetachingEvent) -> None:
        """Handler for `storage_detaching` events."""
        # in the case where there may be replication recovery may be possible
        if self.charm.state.brokers and len(self.charm.state.brokers) > 1:
            self.charm._set_status(Status.REMOVED_STORAGE)
        else:
            self.charm._set_status(Status.REMOVED_STORAGE_NO_REPL)

        self.on.config_changed.emit()

    def _restart(self, event: EventBase) -> None:
        """Handler for `rolling_ops` restart events."""
        # only attempt restart if service is already active
        if not self.healthy:
            event.defer()
            return

        self.charm.workload.restart()

        # FIXME: This logic should be improved as part of ticket DPE-3155
        # For more information, please refer to https://warthogs.atlassian.net/browse/DPE-3155
        time.sleep(10.0)

        if self.charm.workload.active():
            logger.info(f'Broker {self.charm.unit.name.split("/")[1]} restarted')
        else:
            logger.error(f"Broker {self.charm.unit.name.split('/')[1]} failed to restart")

    def _disable_enable_restart(self, event: RunWithLock) -> None:
        """Handler for `rolling_ops` disable_enable restart events."""
        if not self.healthy:
            logger.warning(f"Broker {self.charm.unit.name.split('/')[1]} is not ready restart")
            event.defer()
            return

        self.charm.workload.disable_enable()
        self.charm.workload.start()

        if self.charm.workload.active():
            logger.info(f'Broker {self.charm.unit.name.split("/")[1]} restarted')
        else:
            logger.error(f"Broker {self.charm.unit.name.split('/')[1]} failed to restart")
            return

    def _set_os_config(self) -> None:
        """Sets sysctl config."""
        try:
            self.charm.sysctl_config.configure(OS_REQUIREMENTS)
        except (sysctl.ApplyError, sysctl.ValidationError, sysctl.CommandError) as e:
            logger.error(f"Error setting values on sysctl: {e.message}")
            self.charm._set_status(Status.SYSCONF_NOT_POSSIBLE)

    @property
    def healthy(self) -> bool:
        """Checks and updates various charm lifecycle states.

        Is slow to fail due to retries, to be used sparingly.

        Returns:
            True if service is alive and active. Otherwise False
        """
        self.charm._set_status(self.charm.state.ready_to_start)
        if not isinstance(self.charm.unit.status, ActiveStatus):
            return False

        if not self.charm.workload.active():
            self.charm._set_status(Status.SNAP_NOT_RUNNING)
            return False

        return True

    def update_client_data(self) -> None:
        """Writes necessary relation data to all related client applications."""
        if not self.charm.unit.is_leader() or not self.healthy:
            return

        for client in self.charm.state.clients:
            if not client.password:
                logger.debug(
                    f"Skipping update of {client.app.name}, user has not yet been added..."
                )
                continue

            client.update(
                {
                    "endpoints": client.bootstrap_server,
                    "zookeeper-uris": client.zookeeper_uris,
                    "consumer-group-prefix": client.consumer_group_prefix,
                    "topic": client.topic,
                    "username": client.username,
                    "password": client.password,
                    "tls": client.tls,
                    "tls-ca": client.tls,  # TODO: fix tls-ca
                }
            )
