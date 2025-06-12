#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Broker role core charm logic."""

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from charms.operator_libs_linux.v2.snap import SnapError
from ops import (
    EventBase,
    InstallEvent,
    Object,
    PebbleReadyEvent,
    SecretChangedEvent,
    StartEvent,
    StorageAttachedEvent,
    StorageDetachingEvent,
    StorageEvent,
    UpdateStatusEvent,
)

from events.actions import ActionEvents
from events.controller import KRaftHandler
from events.oauth import OAuthHandler
from events.provider import KafkaProvider
from events.upgrade import KafkaDependencyModel, KafkaUpgrade
from events.zookeeper import ZooKeeperHandler
from health import KafkaHealth
from literals import (
    BROKER,
    CONTAINER,
    CONTROLLER,
    DEPENDENCIES,
    GROUP,
    PEER,
    PROFILE_TESTING,
    REL_NAME,
    USER_ID,
    Status,
)
from managers.auth import AuthManager
from managers.balancer import BalancerManager
from managers.config import TESTING_OPTIONS, ConfigManager
from managers.k8s import K8sManager
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

        self.workload = KafkaWorkload(
            container=(
                self.charm.unit.get_container(CONTAINER) if self.charm.substrate == "k8s" else None
            )
        )

        self.tls_manager = TLSManager(
            state=self.charm.state,
            workload=self.workload,
            substrate=self.charm.substrate,
            config=self.charm.config,
        )

        # Fast exit after workload instantiation, but before any event observer
        if not any(role in self.charm.config.roles for role in [BROKER.value, CONTROLLER.value]):
            return

        self.health = KafkaHealth(self) if self.charm.substrate == "vm" else None
        self.upgrade = KafkaUpgrade(
            self,
            substrate=self.charm.substrate,
            dependency_model=KafkaDependencyModel(
                **DEPENDENCIES  # pyright: ignore[reportArgumentType]
            ),
        )
        self.action_events = ActionEvents(self)

        if not self.charm.state.runs_controller:
            self.zookeeper = ZooKeeperHandler(self)

        self.provider = KafkaProvider(self)
        self.oauth = OAuthHandler(self)
        self.kraft = KRaftHandler(self)

        # MANAGERS

        self.config_manager = ConfigManager(
            state=self.charm.state,
            workload=self.workload,
            config=self.charm.config,
            current_version=self.upgrade.current_version,
        )
        self.auth_manager = AuthManager(
            state=self.charm.state,
            workload=self.workload,
            kafka_opts=self.config_manager.kafka_opts,
            log4j_opts=self.config_manager.tools_log4j_opts,
        )
        self.k8s_manager = K8sManager(
            pod_name=self.charm.state.unit_broker.pod_name, namespace=self.charm.model.name
        )
        self.balancer_manager = BalancerManager(self)

        self.framework.observe(getattr(self.charm.on, "install"), self._on_install)
        self.framework.observe(getattr(self.charm.on, "start"), self._on_start)

        if self.charm.substrate == "k8s":
            self.framework.observe(getattr(self.charm.on, "kafka_pebble_ready"), self._on_start)

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

    def _on_install(self, event: InstallEvent) -> None:
        """Handler for `install` event."""
        if not self.workload.container_can_connect:
            event.defer()
            return

        self.charm.unit.set_workload_version(self.workload.get_version())
        self.config_manager.set_environment()

        # any external services must be created before setting of properties
        self.update_external_services()

        if self.charm.config.profile == PROFILE_TESTING:
            logger.info(
                "Kafka is deployed with the 'testing' profile."
                "The following properties will be set:\n"
                f"{TESTING_OPTIONS}"
            )

    def _on_start(self, event: StartEvent | PebbleReadyEvent) -> None:  # noqa: C901
        """Handler for `start` or `pebble-ready` events."""
        if not self.workload.container_can_connect:
            event.defer()
            return

        if self.charm.state.peer_relation:
            self.charm.state.unit_broker.update(
                {"cores": str(self.balancer_manager.cores), "rack": self.config_manager.rack}
            )

        # don't want to run default start/pebble-ready events during upgrades
        if not self.upgrade.idle:
            return

        current_status = self.charm.state.ready_to_start
        if current_status is not Status.ACTIVE:
            self.charm._set_status(current_status)
            event.defer()
            return

        self.update_external_services()

        # required settings given zookeeper connection config has been created
        self.config_manager.set_server_properties()
        self.config_manager.set_zk_jaas_config()
        self.config_manager.set_client_properties()

        # during pod-reschedules (e.g upgrades or otherwise) we lose all files
        # need to manually add-back key/truststores
        if (
            self.charm.state.cluster.tls_enabled
            and self.charm.state.unit_broker.certificate
            and self.charm.state.unit_broker.ca
        ):  # TLS is probably completed
            self.tls_manager.set_server_key()
            self.tls_manager.set_ca()
            self.tls_manager.set_chain()
            self.tls_manager.set_certificate()
            self.tls_manager.set_bundle()
            self.tls_manager.set_truststore()
            self.tls_manager.set_keystore()

        # start kafka service
        self.workload.start()
        logger.info("Kafka service started")

        # TODO: Update users. Not sure if this is the best place, as cluster might be still
        # stabilizing.
        # if self.charm.state.kraft_mode and self.charm.state.runs_broker:
        #     for username, password in self.charm.state.cluster.internal_user_credentials.items():
        #         try:
        #             self.auth_manager.add_user(
        #                username=username, password=password, zk_auth=False, internal=True,
        #             )
        #         except subprocess.CalledProcessError:
        #             logger.warning("Error adding users, cluster might not be ready yet")
        #             logger.error(f"\n\tOn start:\nAdding user {username} failed. Let the rest of the hook run\n")
        #             # event.defer()
        #             continue

        # service_start might fail silently, confirm with ZK if kafka is actually connected
        self.charm.on.update_status.emit()

        # only log once on successful 'on-start' run
        if not self.charm.pending_inactive_statuses:
            logger.info(f'Broker {self.charm.unit.name.split("/")[1]} connected')

    def _on_config_changed(self, event: EventBase) -> None:
        """Generic handler for most `config_changed` events across relations."""
        # only overwrite properties if service is already active
        if not self.upgrade.idle or not self.healthy:
            event.defer()
            return

        # Load current properties set in the charm workload
        properties = self.workload.read(self.workload.paths.server_properties)
        properties_changed = set(properties) ^ set(self.config_manager.server_properties)

        zk_jaas = self.workload.read(self.workload.paths.zk_jaas)
        zk_jaas_changed = set(zk_jaas) ^ set(self.config_manager.jaas_config.splitlines())

        current_sans = self.tls_manager.get_current_sans()

        if not (properties and zk_jaas):
            # Event fired before charm has properly started
            event.defer()
            return

        current_sans_ip = set(current_sans["sans_ip"]) if current_sans else set()
        expected_sans_ip = set(self.tls_manager.build_sans()["sans_ip"]) if current_sans else set()
        sans_ip_changed = current_sans_ip ^ expected_sans_ip

        current_sans_dns = set(current_sans["sans_dns"]) if current_sans else set()
        expected_sans_dns = (
            set(self.tls_manager.build_sans()["sans_dns"]) if current_sans else set()
        )

        sans_dns_changed = (current_sans_dns ^ expected_sans_dns) - {
            # we omit 'kafka/{unit_id}' and 'kafka' here to avoid a bug with Digicert not supporting '/' characters in SANs
            # Digicert truncates the 'kafka/{unit_id}' to just 'kafka'
            # i.e don't assume we need new certs if 'diff' includes those value, as these SANs aren't typically used anyway
            self.charm.state.unit_broker.unit.name,
            self.charm.state.cluster.app.name,
        }

        # update environment
        self.config_manager.set_environment()
        self.charm.unit.set_workload_version(self.workload.get_version())

        if sans_ip_changed or sans_dns_changed:
            logger.info(
                (
                    f'Broker {self.charm.unit.name.split("/")[1]} updating certificate SANs - '
                    f"OLD SANs IP = {current_sans_ip - expected_sans_ip}, "
                    f"NEW SANs IP = {expected_sans_ip - current_sans_ip}, "
                    f"OLD SANs DNS = {current_sans_dns - expected_sans_dns}, "
                    f"NEW SANs DNS = {expected_sans_dns - current_sans_dns}"
                )
            )
            self.charm.tls.certificates.on.certificate_expiring.emit(
                certificate=self.charm.state.unit_broker.certificate,
                expiry=datetime.now().isoformat(),
            )  # new cert will eventually be dynamically loaded by the broker
            self.charm.state.unit_broker.update(
                {"certificate": ""}
            )  # ensures only single requested new certs, will be replaced on new certificate-available event

            return  # early return here to ensure new node cert arrives before updating advertised.listeners

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

        # update these whenever possible
        self.config_manager.set_client_properties()  # to ensure clients have fresh data
        self.update_external_services()  # in case of IP changes or pod reschedules
        self.charm.state.unit_broker.unit.set_ports(  # in case of listeners changes
            *[listener.port for listener in self.config_manager.all_listeners]
        )

        # Update truststore if needed.
        self.charm.tls.update_truststore()

        # If Kafka is related to client charms, update their information.
        if self.model.relations.get(REL_NAME, None) and self.charm.unit.is_leader():
            self.update_client_data()

        if self.charm.state.peer_cluster_orchestrator_relation and self.charm.unit.is_leader():
            self.update_peer_cluster_data()

    def _on_update_status(self, _: UpdateStatusEvent) -> None:
        """Handler for `update-status` events."""
        if not self.upgrade.idle or not self.healthy:
            return

        if not self.charm.state.kraft_mode:
            if not self.charm.state.zookeeper.broker_active():
                self.charm._set_status(Status.ZK_NOT_CONNECTED)
                return

        # NOTE for situations like IP change and late integration with rack-awareness charm.
        # If properties have changed, the broker will restart.
        self.charm.on.config_changed.emit()

        try:
            if self.health and not self.health.machine_configured():
                self.charm._set_status(Status.SYSCONF_NOT_OPTIMAL)
                return
        except SnapError as e:
            logger.debug(f"Error: {e}")
            self.charm._set_status(Status.BROKER_NOT_RUNNING)
            return

    def _on_secret_changed(self, event: SecretChangedEvent) -> None:
        """Handler for `secret_changed` events."""
        if not event.secret.label or not self.charm.state.cluster.relation:
            return

        if event.secret.label == self.charm.state.cluster.data_interface._generate_secret_label(
            PEER,
            self.charm.state.cluster.relation.id,
            "extra",  # pyright: ignore[reportArgumentType] -- Changes with the https://github.com/canonical/data-platform-libs/issues/124
        ):
            # TODO: figure out why creating internal credentials setting doesn't trigger changed event here
            self.charm.on.config_changed.emit()

    def _on_storage_attached(self, event: StorageAttachedEvent) -> None:
        """Handler for `storage_attached` events."""
        if not self.workload.container_can_connect or not self.charm.state.peer_relation:
            event.defer()
            return

        self.charm.state.unit_broker.update({"storages": self.balancer_manager.storages})

        # FIXME: if KRaft, don't execute
        if self.charm.substrate == "vm" and not self.charm.state.kraft_mode:
            # new dirs won't be used until topic partitions are assigned to it
            # either automatically for new topics, or manually for existing
            # set status only for running services, not on startup
            # FIXME re-add this
            self.workload.exec(["chmod", "-R", "750", f"{self.workload.paths.data_path}"])
            self.workload.exec(
                [
                    "bash",
                    "-c",
                    f"""find {self.workload.paths.data_path} -type f -name meta.properties -delete || true""",
                ]
            )

        # all mounted data dirs should have correct ownership
        self.workload.exec(
            ["chown", "-R", f"{USER_ID}:{GROUP}", f"{self.workload.paths.data_path}"]
        )

        # run this regardless of role, needed for cloud storages + ceph
        for storage in self.charm.state.log_dirs.split(","):
            self.workload.exec(["rm", "-rf", f"{storage}/lost+found"])

        # checks first whether the broker is active before warning
        if self.workload.active():
            # new dirs won't be used until topic partitions are assigned to it
            # either automatically for new topics, or manually for existing
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
        current_status = self.charm.state.ready_to_start
        if current_status is not Status.ACTIVE:
            self.charm._set_status(current_status)
            return False

        if not self.workload.active():
            self.charm._set_status(Status.BROKER_NOT_RUNNING)
            return False

        return True

    def update_external_services(self) -> None:
        """Attempts to update any external Kubernetes services."""
        if not self.charm.substrate == "k8s":
            return

        if self.charm.config.expose_external:
            # every unit attempts to create a bootstrap service
            # if exists, will silently continue
            self.k8s_manager.apply_service(service=self.k8s_manager.build_bootstrap_services())

            # creating the per-broker listener services
            for auth in self.charm.state.enabled_auth:
                listener_service = self.k8s_manager.build_listener_service(auth)
                self.k8s_manager.apply_service(service=listener_service)

    def update_client_data(self) -> None:
        """Writes necessary relation data to all related client applications."""
        if not self.charm.unit.is_leader() or not self.healthy or not self.charm.balancer.healthy:
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
                    "tls-ca": self.charm.state.unit_broker.ca,
                }
            )

    def update_peer_cluster_data(self) -> None:
        """Writes updated relation data to other peer_cluster apps."""
        if not self.charm.unit.is_leader() or not self.healthy:
            return

        self.charm.state.peer_cluster.update(
            {
                "roles": self.charm.state.roles,
                "broker-username": self.charm.state.peer_cluster.broker_username,
                "broker-password": self.charm.state.peer_cluster.broker_password,
                "broker-uris": self.charm.state.peer_cluster.broker_uris,
                "cluster-uuid": self.charm.state.peer_cluster.cluster_uuid,
                "racks": str(self.charm.state.peer_cluster.racks),
                "broker-capacities": json.dumps(self.charm.state.peer_cluster.broker_capacities),
                "zk-uris": self.charm.state.peer_cluster.zk_uris,
                "zk-username": self.charm.state.peer_cluster.zk_username,
                "zk-password": self.charm.state.peer_cluster.zk_password,
            }
        )
