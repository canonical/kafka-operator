#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Broker role core charm logic."""

import json
import logging
from subprocess import CalledProcessError
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
from ops.pebble import ExecError

from core.models import SecretGroup
from events.actions import ActionEvents
from events.controller import KRaftHandler
from events.oauth import OAuthHandler
from events.provider import KafkaProvider
from events.user_secrets import SecretsHandler
from health import KafkaHealth
from literals import (
    BROKER,
    CONTAINER,
    CONTROLLER,
    GROUP,
    PEER,
    PROFILE_TESTING,
    USER_ID,
    Status,
)
from managers.auth import AuthManager
from managers.balancer import BalancerManager
from managers.config import TESTING_OPTIONS, ConfigManager
from managers.controller import ControllerManager
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
        self.controller_manager = ControllerManager(self.charm.state, self.workload)

        # Fast exit after workload instantiation, but before any event observer
        if not any(role in self.charm.config.roles for role in [BROKER.value, CONTROLLER.value]):
            return

        self.health = KafkaHealth(self) if self.charm.substrate == "vm" else None

        self.action_events = ActionEvents(self)
        self.user_secrets = SecretsHandler(self)

        self.provider = KafkaProvider(self)
        self.oauth = OAuthHandler(self)
        self.kraft = KRaftHandler(self)

        # MANAGERS

        self.config_manager = ConfigManager(
            state=self.charm.state,
            workload=self.workload,
            config=self.charm.config,
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
        if not self.workload.container_can_connect or not self.charm.refresh:
            event.defer()
            return

        if self.charm.state.peer_relation:
            self.charm.state.unit_broker.update(
                {"cores": str(self.balancer_manager.cores), "rack": self.config_manager.rack}
            )

        # don't want to run default start/pebble-ready events during upgrades
        if self.charm.refresh.in_progress:
            return

        # Internal TLS setup required?
        if all(
            [
                not self.charm.state.unit_broker.peer_certs.ready,
                not self.charm.state.internal_ca,
                self.charm.unit.is_leader(),
            ]
        ):
            # Generate internal CA
            generated_ca = self.tls_manager.generate_internal_ca()
            self.charm.state.internal_ca = generated_ca.ca
            self.charm.state.internal_ca_key = generated_ca.ca_key

        # Now generate unit's self-signed certs
        self.setup_internal_tls()

        current_status = self.charm.state.ready_to_start
        if current_status is not Status.ACTIVE:
            self.charm._set_status(current_status)
            event.defer()
            return

        self.kraft.format_storages()
        self.update_external_services()
        self.update_ip_addresses()

        self.config_manager.set_server_properties()
        self.config_manager.set_client_properties()

        # during pod-reschedules (e.g upgrades or otherwise) we lose all files
        # need to manually add-back key/truststores
        if (
            self.charm.state.cluster.tls_enabled
            and self.charm.state.unit_broker.client_certs.certificate
            and self.charm.state.unit_broker.client_certs.ca
        ):  # TLS is probably completed
            self.tls_manager.configure()

        # start kafka service
        self.workload.start()
        logger.info("Kafka service started")

        # service_start might fail silently, confirm with ZK if kafka is actually connected
        self.charm.on.update_status.emit()

        # only log once on successful 'on-start' run
        if not self.charm.pending_inactive_statuses:
            logger.info(f'Broker {self.charm.unit.name.split("/")[1]} connected')

    def _handle_configuration_updates(self, event: EventBase) -> None:
        """Handle configuration property updates and restart if needed.

        Helper method to config_changed event.
        """
        if not self.workload.active():
            # shouldn't happen, but just in case
            logger.warning("Kafka service not active during config_changed event. Deferring...")
            return

        properties_changed = self.config_manager.properties_changed()
        if properties_changed:
            logger.info(
                f'Broker {self.charm.unit.name.split("/")[1]} updating config - '
                f"PROPERTIES CHANGED = {len(properties_changed)} properties"
            )
            self.config_manager.set_server_properties()

        if any([properties_changed, self.charm.state.tls_rotate, self.charm.tls.certs_updated]):
            if isinstance(event, StorageEvent):  # to get new storages
                self.controller_manager.format_storages(
                    uuid=self.charm.state.peer_cluster.cluster_uuid,
                    internal_user_credentials=self.charm.state.cluster.internal_user_credentials,
                    initial_controllers=f"{self.charm.state.peer_cluster.bootstrap_unit_id}@{self.charm.state.peer_cluster.bootstrap_controller}:{self.charm.state.peer_cluster.bootstrap_replica_id}",
                )
                self.charm.on[f"{self.charm.restart.name}"].acquire_lock.emit(
                    callback_override="_disable_enable_restart_broker"
                )
            else:
                self.charm.on[f"{self.charm.restart.name}"].acquire_lock.emit()

    def _handle_broker_service_updates(self) -> None:
        """Handle updates to broker services, client data, and other post-configuration tasks."""
        # update these whenever possible
        self.config_manager.set_client_properties()  # to ensure clients have fresh data
        self.update_external_services()  # in case of IP changes or pod reschedules
        if self.charm.state.runs_broker:
            self.charm.state.unit_broker.unit.set_ports(  # in case of listeners changes
                *[listener.port for listener in self.config_manager.all_listeners]
            )
        elif self.charm.state.runs_controller_only:
            self.charm.state.unit_broker.unit.set_ports(
                *[listener.port for listener in self.config_manager.controller_listeners]
            )

        # Update IP addresses based on current network bindings.
        self.update_ip_addresses()

        # The order is important here, first update the credentials cache,
        # then the client relation data.
        self.update_credentials_cache()
        self.provider.update_client_data()

        if self.charm.state.peer_cluster_orchestrator_relation and self.charm.unit.is_leader():
            self.update_peer_cluster_data()

    def _on_config_changed(self, event: EventBase) -> None:
        """Generic handler for most `config_changed` events across relations."""
        if self.charm.refresh_not_ready or not self.healthy:
            event.defer()
            return

        properties = self.workload.read(self.workload.paths.server_properties)
        if not properties:
            event.defer()
            return

        self.config_manager.set_environment()

        should_continue = self.charm.tls.config_changed_rotation(event)
        if not should_continue:
            return

        self._handle_configuration_updates(event)
        self._handle_broker_service_updates()
        self.charm.tls.handle_config_changed_tls_updates()

    def _on_update_status(self, _: UpdateStatusEvent) -> None:
        """Handler for `update-status` events."""
        if self.charm.refresh_not_ready or not self.healthy:
            return

        # NOTE for situations like IP change and late integration with rack-awareness charm.
        # If properties have changed, the broker will restart.
        self.charm.on.config_changed.emit()

        # remove temporary trust aliases if they're no longer needed.
        if (
            self.tls_manager.peer_truststore_has_temporary_aliases
            and self.tls_manager.both_apps_trust_new_bundle()
        ):
            logger.info("Removing decommissioned CA from truststore.")
            self.tls_manager.rebuild_truststore()
            self.charm.on[f"{self.charm.restart.name}"].acquire_lock.emit()

        try:
            if self.health and not self.health.machine_configured():
                self.charm._set_status(Status.SYSCONF_NOT_OPTIMAL)
                return
        except SnapError as e:
            logger.debug(f"Error: {e}")
            self.charm._set_status(Status.SERVICE_NOT_RUNNING)
            return

    def _on_secret_changed(self, event: SecretChangedEvent) -> None:
        """Handler for `secret_changed` events."""
        if not event.secret.label or not self.charm.state.peer_relation:
            return

        if event.secret.label == self.charm.state.cluster.repository._generate_secret_label(
            self.charm.state.peer_relation, SecretGroup("extra")
        ):
            self.charm.on.config_changed.emit()

    def _on_storage_attached(self, event: StorageAttachedEvent) -> None:
        """Handler for `storage_attached` events."""
        if not self.workload.container_can_connect or not self.charm.state.peer_relation:
            event.defer()
            return

        self.charm.state.unit_broker.update({"storages": self.balancer_manager.storages})

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

    def setup_internal_tls(self) -> None:
        """Generates a self-signed certificate if required and writes all necessary TLS configuration for internal TLS."""
        if self.charm.state.unit_broker.peer_certs.ready:
            self.tls_manager.configure()
            return

        self_signed_cert = self.tls_manager.generate_self_signed_certificate()
        if not self_signed_cert:
            return

        self.charm.state.unit_broker.peer_certs.set_self_signed(self_signed_cert)
        self.charm.state.unit_broker.peer_certs.rotate = True
        self.tls_manager.configure()

        if self.charm.unit.is_leader():
            # If leader, also set the peer cluster chain. Leads to no-op in KRaft single mode.
            self.charm.state.peer_cluster_ca = self.charm.state.unit_broker.peer_certs.bundle

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
            self.charm._set_status(Status.SERVICE_NOT_RUNNING)
            return False

        if self.charm.state.runs_broker and not self.kraft.controller_manager.broker_active():
            self.charm._set_status(Status.BROKER_NOT_CONNECTED)

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

    def update_peer_cluster_data(self) -> None:
        """Writes updated relation data to other peer_cluster apps."""
        if not self.charm.unit.is_leader() or not self.healthy:
            return

        # Update peer-cluster chain of trust
        self.charm.state.peer_cluster_ca = self.charm.state.unit_broker.peer_certs.bundle

        # Optimization: cache peer_cluster to avoid multiple loadings
        peer_cluster_state = self.charm.state.peer_cluster

        self.charm.state.peer_cluster.update(
            {
                "roles": self.charm.state.roles,
                "broker-username": peer_cluster_state.broker_username,
                "broker-password": peer_cluster_state.broker_password,
                "broker-uris": peer_cluster_state.broker_uris,
                "cluster-uuid": peer_cluster_state.cluster_uuid,
                "racks": str(peer_cluster_state.racks),
                "broker-capacities": json.dumps(peer_cluster_state.broker_capacities),
                "super-users": self.charm.state.super_users,
            }
        )

    def update_credentials_cache(self) -> None:
        """Ensures the broker's credentials cache is updated after restart."""
        if not all([self.charm.unit.is_leader(), self.charm.state.runs_broker, self.healthy]):
            return

        if not self.workload.ping(self.charm.state.bootstrap_server_internal):
            return

        try:
            users = self.auth_manager.get_users()
        except (CalledProcessError, ExecError) as e:
            # probably the cluster is not healthy, we'll check in the next update-status
            logger.error(e)
            return

        # Update client properties first, to ensure it's consistent with latest listener config
        self.config_manager.set_client_properties()

        for client in self.charm.state.clients:

            if not client.password:
                # client not setup yet.
                continue

            if client.username in users:
                # no need to re-add the user.
                continue

            self.auth_manager.add_user(client.username, client.password)

    def update_peer_truststore_state(self, force: bool = False) -> None:
        """Updates the relation data reflecting the unit/app truststore state on respective data bags.

        Args:
            force (bool, optional): Bypass the check of whether a restart is performed after truststore modification time. Defaults to False.
        """
        truststore_path = self.workload.root / self.workload.paths.peer_truststore

        if not truststore_path.exists():
            return

        if not force and self.workload.last_restart <= self.workload.modify_time(
            self.workload.paths.peer_truststore
        ):
            # We shouldn't update the relation data, because we need a restart first.
            return

        trusted_certs = [
            self.tls_manager.bytes_to_keytool_hash(_hash, sep="")
            for _hash in self.tls_manager.peer_trusted_certificates.values()
        ]

        self.charm.state.unit_broker.peer_certs.trusted_certificates = trusted_certs

        if self.charm.unit.is_leader():
            self.charm.state.refresh_peer_cluster_trust_state()

    def update_ip_addresses(self) -> None:
        """Update unit databag with current IP addresses associated with this unit.

        This method will add peer and client addresses taking network binds into account.
        """
        self.charm.state.unit_broker.update_peer_ip_address()

        for client in self.charm.state.clients:
            if not client.relation:
                continue

            self.charm.state.unit_broker.update_relation_ip_address(client.relation, client.ip)
