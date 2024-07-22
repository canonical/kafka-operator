"""Broker role core charm logic."""

import logging
from typing import TYPE_CHECKING

from charms.operator_libs_linux.v1.snap import SnapError
from ops import (
    ActiveStatus,
    EventBase,
    InstallEvent,
    Object,
    SecretChangedEvent,
    StartEvent,
    StorageAttachedEvent,
    StorageDetachingEvent,
    StorageEvent,
    UpdateStatusEvent,
)

from events.oauth import OAuthHandler
from events.password_actions import PasswordActionEvents
from events.provider import KafkaProvider
from events.tls import TLSHandler
from events.upgrade import KafkaDependencyModel, KafkaUpgrade
from events.zookeeper import ZooKeeperHandler
from health import KafkaHealth
from literals import (
    BROKER,
    DEPENDENCIES,
    GROUP,
    PEER,
    REL_NAME,
    USER,
    Status,
)
from managers.auth import AuthManager
from managers.balancer import BalancerManager
from managers.config import ConfigManager
from managers.tls import TLSManager
from workload import KafkaWorkload

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)


class BrokerOperator(Object):
    """Charmed Operator for Kafka."""

    def __init__(self, charm) -> None:
        super().__init__(charm, BROKER.value)
        self.charm: "KafkaCharm" = charm

        self.workload = KafkaWorkload()

        # Fast exit after workload instantiation, but before any event observer
        if BROKER.value not in self.charm.config.roles:
            return

        self.health = KafkaHealth(self)
        self.upgrade = KafkaUpgrade(
            self,
            dependency_model=KafkaDependencyModel(
                **DEPENDENCIES  # pyright: ignore[reportGeneralTypeIssues, reportArgumentType]
            ),
        )
        self.password_action_events = PasswordActionEvents(self)
        self.zookeeper = ZooKeeperHandler(self)
        self.oauth = OAuthHandler(self)
        self.tls = TLSHandler(self)
        self.provider = KafkaProvider(self)

        # MANAGERS

        self.config_manager = ConfigManager(
            state=self.charm.state,
            workload=self.workload,
            config=self.charm.config,
            current_version=self.upgrade.current_version,
        )
        self.tls_manager = TLSManager(
            state=self.charm.state, workload=self.workload, substrate=self.charm.substrate
        )
        self.auth_manager = AuthManager(
            state=self.charm.state,
            workload=self.workload,
            kafka_opts=self.config_manager.kafka_opts,
            log4j_opts=self.config_manager.tools_log4j_opts,
        )

        self.balancer_manager = BalancerManager(self)

        self.framework.observe(getattr(self.charm.on, "install"), self._on_install)
        self.framework.observe(getattr(self.charm.on, "start"), self._on_start)
        self.framework.observe(getattr(self.charm.on, "config_changed"), self._on_config_changed)
        self.framework.observe(getattr(self.charm.on, "update_status"), self._on_update_status)
        self.framework.observe(getattr(self.charm.on, "secret_changed"), self._on_secret_changed)

        self.framework.observe(self.charm.on[PEER].relation_changed, self._on_config_changed)

        self.framework.observe(
            getattr(self.charm.on, "data_storage_attached"), self._on_storage_attached
        )
        self.framework.observe(
            getattr(self.charm.on, "data_storage_detaching"), self._on_storage_detaching
        )

    def _on_install(self, _: InstallEvent) -> None:
        """Handler for `install` event."""
        self.config_manager.set_environment()
        self.charm.unit.set_workload_version(self.workload.get_version())

    def _on_start(self, event: StartEvent) -> None:
        """Handler for `start` event."""
        if self.charm.state.peer_relation:
            self.charm.state.unit_broker.update(
                {"cores": str(self.balancer_manager.cores), "rack": self.config_manager.rack}
            )

        self.charm._set_status(self.charm.state.ready_to_start)
        if not isinstance(self.charm.unit.status, ActiveStatus):
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
        self.charm.on.update_status.emit()

        # only log once on successful 'on-start' run
        if isinstance(self.charm.unit.status, ActiveStatus):
            logger.info(f'Broker {self.charm.unit.name.split("/")[1]} connected')

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
        zk_jaas_changed = set(zk_jaas) ^ set(self.config_manager.jaas_config.splitlines())

        if not properties or not zk_jaas:
            # Event fired before charm has properly started
            event.defer()
            return

        # update environment
        self.config_manager.set_environment()
        self.charm.unit.set_workload_version(self.workload.get_version())

        if zk_jaas_changed:
            clean_broker_jaas = [conf.strip() for conf in zk_jaas]
            clean_config_jaas = [
                conf.strip() for conf in self.config_manager.jaas_config.splitlines()
            ]
            logger.info(
                (
                    f'Broker {self.charm.unit.name.split("/")[1]} updating JAAS config - '
                    f"OLD JAAS = {set(clean_broker_jaas) - set(clean_config_jaas)}, "
                    f"NEW JAAS = {set(clean_config_jaas) - set(clean_broker_jaas)}"
                )
            )
            self.config_manager.set_zk_jaas_config()

        if properties_changed:
            logger.info(
                (
                    f'Broker {self.charm.unit.name.split("/")[1]} updating config - '
                    f"OLD PROPERTIES = {set(properties) - set(self.config_manager.server_properties)}, "
                    f"NEW PROPERTIES = {set(self.config_manager.server_properties) - set(properties)}"
                )
            )
            self.config_manager.set_server_properties()

        if zk_jaas_changed or properties_changed:
            if isinstance(event, StorageEvent):  # to get new storages
                self.charm.on[f"{self.charm.restart.name}"].acquire_lock.emit(
                    callback_override="_disable_enable_restart_broker"
                )
            else:
                self.charm.on[f"{self.charm.restart.name}"].acquire_lock.emit()

        # update client_properties whenever possible
        self.config_manager.set_client_properties()

        # If Kafka is related to client charms, update their information.
        if self.model.relations.get(REL_NAME, None) and self.charm.unit.is_leader():
            self.update_client_data()

    def _on_update_status(self, _: UpdateStatusEvent) -> None:
        """Handler for `update-status` events."""
        if not self.healthy or not self.upgrade.idle:
            return

        if not self.charm.state.zookeeper.broker_active():
            self.charm._set_status(Status.ZK_NOT_CONNECTED)
            return

        # NOTE for situations like IP change and late integration with rack-awareness charm.
        # If properties have changed, the broker will restart.
        self.charm.on.config_changed.emit()

        try:
            if not self.health.machine_configured():
                self.charm._set_status(Status.SYSCONF_NOT_OPTIMAL)
                return
        except SnapError as e:
            logger.debug(f"Error: {e}")
            self.charm._set_status(Status.BROKER_NOT_RUNNING)
            return

        self.charm._set_status(Status.ACTIVE)

    def _on_secret_changed(self, event: SecretChangedEvent) -> None:
        """Handler for `secret_changed` events."""
        if not event.secret.label or not self.charm.state.cluster.relation:
            return

        if event.secret.label == self.charm.state.cluster.data_interface._generate_secret_label(
            PEER,
            self.charm.state.cluster.relation.id,
            "extra",  # pyright: ignore[reportArgumentType] -- Changes with the https://github.com/canonical/data-platform-libs/issues/124
        ):
            self.charm.on.config_changed.emit()

    def _on_storage_attached(self, event: StorageAttachedEvent) -> None:
        """Handler for `storage_attached` events."""
        # storage-attached usually fires before relation-created/joined
        if not self.charm.state.peer_relation:
            event.defer()
            return

        self.charm.state.unit_broker.update({"storages": self.balancer_manager.storages})

        # new dirs won't be used until topic partitions are assigned to it
        # either automatically for new topics, or manually for existing
        # set status only for running services, not on startup
        self.workload.exec(f"chmod -R 750 {self.workload.paths.data_path}")
        self.workload.exec(f"chown -R {USER}:{GROUP} {self.workload.paths.data_path}")
        self.workload.exec(
            f"""find {self.workload.paths.data_path} -type f -name "meta.properties" -delete || true"""
        )
        if self.workload.active():
            self.charm._set_status(Status.ADDED_STORAGE)
            # We need the event handler to know about the original event
            self._on_config_changed(event)

    def _on_storage_detaching(self, _: StorageDetachingEvent) -> None:
        """Handler for `storage_detaching` events."""
        # in the case where there may be replication recovery may be possible
        if self.charm.state.brokers and len(self.charm.state.brokers) > 1:
            self.charm._set_status(Status.REMOVED_STORAGE)
        else:
            self.charm._set_status(Status.REMOVED_STORAGE_NO_REPL)

        self.charm.state.unit_broker.update({"storages": self.balancer_manager.storages})
        self.charm.on.config_changed.emit()

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

        if not self.workload.active():
            self.charm._set_status(Status.BROKER_NOT_RUNNING)
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
