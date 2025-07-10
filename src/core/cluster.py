#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Objects representing the state of KafkaCharm."""

import logging
import os
from functools import cached_property
from ipaddress import IPv4Address, IPv6Address
from typing import TYPE_CHECKING, Any

from charms.data_platform_libs.v0.data_interfaces import (
    SECRET_GROUPS,
    DataPeerData,
    DataPeerOtherUnitData,
    DataPeerUnitData,
    KafkaProviderData,
    ProviderData,
    RequirerData,
)
from lightkube.core.exceptions import ApiError as LightKubeApiError
from ops import Object, Relation
from ops.model import Unit
from tenacity import retry, retry_if_exception_cause_type, stop_after_attempt, wait_fixed

from core.models import (
    BrokerCapacities,
    KafkaBroker,
    KafkaClient,
    KafkaCluster,
    OAuth,
    PeerCluster,
)
from literals import (
    ADMIN_USER,
    BALANCER,
    BROKER,
    CERTIFICATE_TRANSFER_RELATION,
    CONTROLLER,
    CONTROLLER_PORT,
    CONTROLLER_USER,
    INTERNAL_USERS,
    KRAFT_NODE_ID_OFFSET,
    MIN_REPLICAS,
    OAUTH_REL_NAME,
    PEER,
    PEER_CLUSTER_ORCHESTRATOR_RELATION,
    PEER_CLUSTER_RELATION,
    REL_NAME,
    SECRETS_UNIT,
    SECURITY_PROTOCOL_PORTS,
    AuthMap,
    Status,
    Substrates,
)

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)

custom_secret_groups = SECRET_GROUPS
setattr(custom_secret_groups, "BROKER", "broker")
setattr(custom_secret_groups, "BALANCER", "balancer")
setattr(custom_secret_groups, "CONTROLLER", "controller")

SECRET_LABEL_MAP = {
    "broker-username": getattr(custom_secret_groups, "BROKER"),
    "broker-password": getattr(custom_secret_groups, "BROKER"),
    "controller-password": getattr(custom_secret_groups, "CONTROLLER"),
    "broker-uris": getattr(custom_secret_groups, "BROKER"),
    "balancer-username": getattr(custom_secret_groups, "BALANCER"),
    "balancer-password": getattr(custom_secret_groups, "BALANCER"),
    "balancer-uris": getattr(custom_secret_groups, "BALANCER"),
}


class PeerClusterOrchestratorData(ProviderData, RequirerData):
    """Broker provider data model."""

    SECRET_LABEL_MAP = SECRET_LABEL_MAP
    SECRET_FIELDS = BROKER.requested_secrets

    # This is to bypass the PrematureDataAccessError, which is irrelevant in this case.
    def _update_relation_data(self, relation: Relation, data: dict[str, str]) -> None:
        """Set values for fields not caring whether it's a secret or not."""
        super(ProviderData, self)._update_relation_data(relation, data)


class PeerClusterData(ProviderData, RequirerData):
    """Broker provider data model."""

    SECRET_LABEL_MAP = SECRET_LABEL_MAP
    SECRET_FIELDS = list(set(BALANCER.requested_secrets) | set(CONTROLLER.requested_secrets))

    # This is to bypass the PrematureDataAccessError, which is irrelevant in this case.
    def _update_relation_data(self, relation: Relation, data: dict[str, str]) -> None:
        """Set values for fields not caring whether it's a secret or not."""
        super(ProviderData, self)._update_relation_data(relation, data)


class ClusterState(Object):
    """Collection of global cluster state for the Kafka services."""

    def __init__(self, charm: "KafkaCharm", substrate: Substrates):
        super().__init__(parent=charm, key="charm_state")
        self.substrate: Substrates = substrate
        self.roles = charm.config.roles
        self.network_bandwidth = charm.config.network_bandwidth
        self.config = charm.config

        self.peer_app_interface = DataPeerData(self.model, relation_name=PEER)
        self.peer_unit_interface = DataPeerUnitData(
            self.model, relation_name=PEER, additional_secret_fields=SECRETS_UNIT
        )
        self.client_provider_interface = KafkaProviderData(self.model, relation_name=REL_NAME)

    # --- RELATIONS ---

    @property
    def peer_relation(self) -> Relation | None:
        """The cluster peer relation."""
        return self.model.get_relation(PEER)

    @property
    def client_relations(self) -> set[Relation]:
        """The relations of all client applications."""
        return set(self.model.relations[REL_NAME])

    @property
    def peer_cluster_orchestrator_relation(self) -> Relation | None:
        """The `peer-cluster-orchestrator` relation that this charm is providing."""
        return self.model.get_relation(PEER_CLUSTER_ORCHESTRATOR_RELATION)

    @property
    def peer_cluster_relation(self) -> Relation | None:
        """The `peer-cluster` relation that this charm is requiring."""
        return self.model.get_relation(PEER_CLUSTER_RELATION)

    @property
    def peer_cluster_orchestrator(self) -> PeerCluster:
        """The state for the related `peer-cluster-orchestrator` application that this charm is requiring from."""
        extra_kwargs: dict[str, Any] = {}

        if self.runs_balancer:
            extra_kwargs.update(
                {
                    "balancer_username": self.cluster.balancer_username,
                    "balancer_password": self.cluster.balancer_password,
                    "balancer_uris": self.cluster.balancer_uris,
                }
            )

        if self.runs_controller:
            extra_kwargs.update(
                {
                    "controller_password": self.cluster.controller_password,
                    "bootstrap_controller": self.cluster.bootstrap_controller,
                    "bootstrap_unit_id": self.cluster.bootstrap_unit_id,
                    "bootstrap_replica_id": self.cluster.bootstrap_replica_id,
                }
            )

        return PeerCluster(
            relation=self.peer_cluster_relation,
            data_interface=PeerClusterData(self.model, PEER_CLUSTER_RELATION),
            **extra_kwargs,
        )

    @property
    def peer_cluster(self) -> PeerCluster:
        """The state for the `peer-cluster-orchestrator` related balancer application."""
        extra_kwargs: dict[str, Any] = {}

        if self.runs_controller or self.runs_balancer:
            extra_kwargs.update(
                {
                    "balancer_username": self.cluster.balancer_username,
                    "balancer_password": self.cluster.balancer_password,
                    "balancer_uris": self.cluster.balancer_uris,
                    "controller_password": self.cluster.controller_password,
                    "bootstrap_controller": self.cluster.bootstrap_controller,
                    "bootstrap_unit_id": self.cluster.bootstrap_unit_id,
                    "bootstrap_replica_id": self.cluster.bootstrap_replica_id,
                }
            )

        # FIXME: `cluster_manager` check instead of running broker
        # must be providing, initialise with necessary broker data
        if self.runs_broker:
            return PeerCluster(
                relation=self.peer_cluster_orchestrator_relation,  # if same app, this will be None and OK
                data_interface=PeerClusterOrchestratorData(
                    self.model, PEER_CLUSTER_ORCHESTRATOR_RELATION
                ),
                broker_username=ADMIN_USER,
                broker_password=self.cluster.internal_user_credentials.get(ADMIN_USER, ""),
                broker_uris=self.bootstrap_server,
                cluster_uuid=self.cluster.cluster_uuid,
                racks=self.racks,
                broker_capacities=self.broker_capacities,
                **extra_kwargs,  # in case of roles=broker,[balancer,controller] on this app
            )

        else:  # must be roles=balancer only then, only load with necessary balancer data
            return self.peer_cluster_orchestrator

    @property
    def oauth_relation(self) -> Relation | None:
        """The OAuth relation."""
        return self.model.get_relation(OAUTH_REL_NAME)

    @property
    def has_mtls_clients(self) -> bool:
        """Returns True if there exists any mTLS client either in `kafka_client` or `certificate_transfer` interfaces, False otherwise."""
        if any(client.mtls_cert for client in self.clients):
            return True

        cert_transfer_relations = set(self.model.relations[CERTIFICATE_TRANSFER_RELATION])
        if cert_transfer_relations:
            return True

        return False

    # --- CORE COMPONENTS ---

    @property
    def unit_broker(self) -> KafkaBroker:
        """The broker state of the current running Unit."""
        return KafkaBroker(
            relation=self.peer_relation,
            data_interface=self.peer_unit_interface,
            component=self.model.unit,
            substrate=self.substrate,
        )

    @property
    def kraft_unit_id(self) -> int:
        """Returns current unit ID in KRaft Quorum Manager."""
        if self.runs_broker and self.runs_controller:
            return KRAFT_NODE_ID_OFFSET + self.unit_broker.unit_id
        return self.unit_broker.unit_id

    @cached_property
    def peer_units_data_interfaces(self) -> dict[Unit, DataPeerOtherUnitData]:
        """The cluster peer relation."""
        if not self.peer_relation or not self.peer_relation.units:
            return {}

        return {
            unit: DataPeerOtherUnitData(model=self.model, unit=unit, relation_name=PEER)
            for unit in self.peer_relation.units
        }

    @property
    def cluster(self) -> KafkaCluster:
        """The cluster state of the current running App."""
        return KafkaCluster(
            relation=self.peer_relation,
            data_interface=self.peer_app_interface,
            component=self.model.app,
        )

    @property
    def brokers(self) -> set[KafkaBroker]:
        """Grabs all servers in the current peer relation, including the running unit server.

        Returns:
            Set of KafkaBrokers in the current peer relation, including the running unit server.
        """
        brokers = set()
        for unit, data_interface in self.peer_units_data_interfaces.items():
            brokers.add(
                KafkaBroker(
                    relation=self.peer_relation,
                    data_interface=data_interface,
                    component=unit,
                    substrate=self.substrate,
                )
            )
        brokers.add(self.unit_broker)

        return brokers

    @property
    def oauth(self) -> OAuth:
        """The oauth relation state."""
        return OAuth(
            relation=self.oauth_relation,
        )

    @property
    def clients(self) -> set[KafkaClient]:
        """The state for all related client Applications."""
        clients = set()
        for relation in self.client_relations:
            if not relation.app:
                continue

            clients.add(
                KafkaClient(
                    relation=relation,
                    data_interface=self.client_provider_interface,
                    component=relation.app,
                    local_app=self.cluster.app,
                    bootstrap_server=self.bootstrap_server,
                    password=self.cluster.client_passwords.get(f"relation-{relation.id}", ""),
                    tls="enabled" if self.cluster.tls_enabled else "disabled",
                )
            )

        return clients

    # ---- GENERAL VALUES ----

    @property
    def bind_address(self) -> IPv4Address | IPv6Address | str:
        """The network binding address from the peer relation."""
        bind_address = None
        if self.peer_relation:
            if binding := self.model.get_binding(self.peer_relation):
                bind_address = binding.network.bind_address

        return bind_address or ""

    @property
    def super_users(self) -> str:
        """Generates all users with super/admin permissions for the cluster from relations.

        Formatting allows passing to the `super.users` property.

        Returns:
            Semicolon delimited string of current super users
        """
        if self.runs_controller_only:
            return self.peer_cluster.super_users

        super_users = set(INTERNAL_USERS)
        super_users.add(CONTROLLER_USER)

        for relation in self.client_relations:
            if not relation or not relation.app:
                continue

            extra_user_roles = relation.data[relation.app].get("extra-user-roles", "")
            password = self.cluster.relation_data.get(f"relation-{relation.id}", None)
            # if passwords are set for client admins, they're good to load
            if "admin" in extra_user_roles and password is not None:
                super_users.add(f"relation-{relation.id}")

        super_users_arg = sorted([f"User:{user}" for user in super_users])

        return ";".join(super_users_arg)

    @property
    def default_auth(self) -> AuthMap:
        """The current enabled auth.protocol for bootstrap."""
        auth_protocol = (
            "SASL_SSL"
            if self.cluster.tls_enabled and self.unit_broker.certificate
            else "SASL_PLAINTEXT"
        )

        # FIXME: will need updating when we support multiple concurrent security.protocols
        # as this is what is sent across the relation, currently SASL only
        return AuthMap(auth_protocol, "SCRAM-SHA-512")

    @property
    def enabled_auth(self) -> list[AuthMap]:
        """The currently enabled auth.protocols and their auth.mechanisms, based on related applications."""
        enabled_auth = []
        if (
            self.client_relations
            or self.runs_balancer
            or BALANCER.value in self.peer_cluster_orchestrator.roles
        ):
            enabled_auth.append(self.default_auth)
        if self.oauth_relation:
            enabled_auth.append(AuthMap(self.default_auth.protocol, "OAUTHBEARER"))
        if self.cluster.mtls_enabled:
            enabled_auth.append(AuthMap("SSL", "SSL"))

        return enabled_auth

    @property
    @retry(
        wait=wait_fixed(5),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_cause_type(LightKubeApiError),
        reraise=True,
    )
    def bootstrap_servers_external(self) -> str:
        """Comma-delimited string of `bootstrap-server` for external access."""
        return ",".join(
            sorted(
                {
                    f"{broker.node_ip}:{self.unit_broker.k8s.get_bootstrap_nodeport(self.default_auth)}"
                    for broker in self.brokers
                }
            )
        )

    @property
    def bootstrap_server(self) -> str:
        """The current Kafka uris formatted for the `bootstrap-server` command flag.

        Returns:
            List of `bootstrap-server` servers
        """
        if not self.peer_relation:
            return ""

        if self.config.expose_external:  # implicitly checks for k8s in structured_config
            # service might not be created yet by the broker
            try:
                return self.bootstrap_servers_external
            except LightKubeApiError as e:
                logger.debug(e)
                return ""

        return ",".join(
            sorted(
                [
                    f"{broker.internal_address}:{SECURITY_PROTOCOL_PORTS[self.default_auth].client}"
                    for broker in self.brokers
                ]
            )
        )

    @property
    def bootstrap_server_internal(self) -> str:
        """Comma-delimited string of `bootstrap-server` command flag for internal access.

        Returns:
            List of `bootstrap-server` servers
        """
        if not self.peer_relation:
            return ""

        return ",".join(
            sorted(
                [
                    f"{broker.internal_address}:{SECURITY_PROTOCOL_PORTS[self.default_auth].internal}"
                    for broker in self.brokers
                ]
            )
        )

    @property
    def bootstrap_controller(self) -> str:
        """Returns the controller listener in the format HOST:PORT."""
        if self.runs_controller:
            return f"{self.unit_broker.internal_address}:{CONTROLLER_PORT}"
        return ""

    @property
    def log_dirs(self) -> str:
        """Builds the necessary log.dirs based on mounted storage volumes.

        Returns:
            String of log.dirs property value to be set
        """
        return ",".join([os.fspath(storage.location) for storage in self.model.storages["data"]])

    @property
    def planned_units(self) -> int:
        """Return the planned units for the charm."""
        return self.model.app.planned_units()

    @property
    def racks(self) -> int:
        """Number of racks for the brokers."""
        return len({broker.rack for broker in self.brokers if broker.rack})

    @property
    def broker_capacities(self) -> BrokerCapacities:
        """The capacities for all Kafka broker."""
        broker_capacities = []
        for broker in sorted(self.brokers, key=lambda broker: broker.unit_id, reverse=True):
            if not all([broker.cores, broker.storages]):
                return {}

            broker_capacities.append(
                {
                    "brokerId": str(broker.broker_id),
                    "capacity": {
                        "DISK": broker.storages,
                        "CPU": {"num.cores": broker.cores},
                        "NW_IN": str(self.network_bandwidth),
                        "NW_OUT": str(self.network_bandwidth),
                    },
                    "doc": "",
                }
            )

        return {"brokerCapacities": broker_capacities}

    @property
    def ready_to_start(self) -> Status:  # noqa: C901
        """Check for active controller relation and adding of inter-broker auth username.

        Returns:
            True if ZK is related and `sync` user has been added. False otherwise.
        """
        if not self.peer_relation:
            return Status.NO_PEER_RELATION

        if self.runs_broker_only and not self.peer_cluster_orchestrator_relation:
            return Status.MISSING_MODE

        for status in [self._broker_status, self._controller_status]:
            if status != Status.ACTIVE:
                return status

        return Status.ACTIVE

    @property
    def balancer_status(self) -> Status:
        """Checks for role=balancer specific readiness."""
        if not self.peer_relation:
            return Status.NO_PEER_RELATION

        if not self.runs_balancer or not self.unit_broker.unit.is_leader():
            return Status.ACTIVE

        if not self.peer_cluster_relation and not self.runs_broker:
            return Status.NO_PEER_CLUSTER_RELATION

        if not self.peer_cluster.broker_connected:
            return Status.NO_BROKER_DATA

        if len(self.peer_cluster.broker_capacities.get("brokerCapacities", [])) < MIN_REPLICAS:
            return Status.NOT_ENOUGH_BROKERS

        return Status.ACTIVE

    @property
    def _broker_status(self) -> Status:  # noqa: C901
        """Checks for role=broker specific readiness."""
        if not self.runs_broker:
            return Status.ACTIVE

        if not self.peer_cluster.bootstrap_controller:
            return Status.NO_BOOTSTRAP_CONTROLLER

        if not self.peer_cluster.controller_password:
            return Status.MISSING_CONTROLLER_PASSWORD

        if not self.cluster.cluster_uuid:
            return Status.NO_CLUSTER_UUID

        if self.cluster.tls_enabled and not self.unit_broker.certificate:
            return Status.NO_CERT

        if not self.cluster.internal_user_credentials:
            return Status.NO_BROKER_CREDS

        return Status.ACTIVE

    @property
    def _controller_status(self) -> Status:
        """Checks for role=controller specific readiness."""
        if not self.runs_controller:
            return Status.ACTIVE

        if not self.peer_cluster_relation and not self.runs_broker:
            return Status.NO_PEER_CLUSTER_RELATION

        if not self.peer_cluster.broker_connected_kraft_mode:
            return Status.NO_BROKER_DATA

        return Status.ACTIVE

    @property
    def runs_balancer(self) -> bool:
        """Is the charm enabling the balancer?"""
        return BALANCER.value in self.roles

    @property
    def runs_broker(self) -> bool:
        """Is the charm enabling the broker(s)?"""
        return BROKER.value in self.roles

    @property
    def runs_controller(self) -> bool:
        """Is the charm enabling the controller?"""
        return CONTROLLER.value in self.roles

    @property
    def runs_broker_only(self) -> bool:
        """Is the charm ONLY running broker in KRaft mode?"""
        return self.runs_broker and not self.runs_controller

    @property
    def runs_controller_only(self) -> bool:
        """Is the charm ONLY running controller in KRaft mode?"""
        return self.runs_controller and not self.runs_broker
