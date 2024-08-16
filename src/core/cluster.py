#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Objects representing the state of KafkaCharm."""

import os
from functools import cached_property
from ipaddress import IPv4Address, IPv6Address
from typing import TYPE_CHECKING, Any

from charms.data_platform_libs.v0.data_interfaces import (
    SECRET_GROUPS,
    DatabaseRequirerData,
    DataPeerData,
    DataPeerOtherUnitData,
    DataPeerUnitData,
    KafkaProviderData,
    ProviderData,
    RequirerData,
)
from ops import Object, Relation
from ops.model import Unit

from core.models import (
    JSON,
    KafkaBroker,
    KafkaClient,
    KafkaCluster,
    OAuth,
    PeerCluster,
    ZooKeeper,
)
from literals import (
    ADMIN_USER,
    BALANCER,
    BROKER,
    INTERNAL_USERS,
    MIN_REPLICAS,
    OAUTH_REL_NAME,
    PEER,
    PEER_CLUSTER_ORCHESTRATOR_RELATION,
    PEER_CLUSTER_RELATION,
    REL_NAME,
    SECRETS_UNIT,
    SECURITY_PROTOCOL_PORTS,
    ZK,
    AuthMap,
    Status,
    Substrates,
)

if TYPE_CHECKING:
    from charm import KafkaCharm

custom_secret_groups = SECRET_GROUPS
setattr(custom_secret_groups, "BROKER", "broker")
setattr(custom_secret_groups, "BALANCER", "balancer")
setattr(custom_secret_groups, "ZOOKEEPER", "zookeeper")

SECRET_LABEL_MAP = {
    "broker-username": getattr(custom_secret_groups, "BROKER"),
    "broker-password": getattr(custom_secret_groups, "BROKER"),
    "broker-uris": getattr(custom_secret_groups, "BROKER"),
    "zk-username": getattr(custom_secret_groups, "ZOOKEEPER"),
    "zk-password": getattr(custom_secret_groups, "ZOOKEEPER"),
    "zk-uris": getattr(custom_secret_groups, "ZOOKEEPER"),
    "balancer-username": getattr(custom_secret_groups, "BALANCER"),
    "balancer-password": getattr(custom_secret_groups, "BALANCER"),
    "balancer-uris": getattr(custom_secret_groups, "BALANCER"),
}


class PeerClusterOrchestratorData(ProviderData, RequirerData):
    """Broker provider data model."""

    SECRET_LABEL_MAP = SECRET_LABEL_MAP
    SECRET_FIELDS = BALANCER.requested_secrets


class PeerClusterData(ProviderData, RequirerData):
    """Broker provider data model."""

    SECRET_LABEL_MAP = SECRET_LABEL_MAP
    SECRET_FIELDS = BROKER.requested_secrets


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
        self.zookeeper_requires_interface = DatabaseRequirerData(
            self.model, relation_name=ZK, database_name=f"/{self.model.app.name}"
        )
        self.client_provider_interface = KafkaProviderData(self.model, relation_name=REL_NAME)

    # --- RELATIONS ---

    @property
    def peer_relation(self) -> Relation | None:
        """The cluster peer relation."""
        return self.model.get_relation(PEER)

    @property
    def zookeeper_relation(self) -> Relation | None:
        """The ZooKeeper relation."""
        return self.model.get_relation(ZK)

    @property
    def client_relations(self) -> set[Relation]:
        """The relations of all client applications."""
        return set(self.model.relations[REL_NAME])

    @property
    def peer_cluster_orchestrator_relations(self) -> set[Relation]:
        """The `peer-cluster-orchestrator` relations that this charm is providing."""
        return set(self.model.relations[PEER_CLUSTER_ORCHESTRATOR_RELATION])

    @property
    def peer_cluster_relation(self) -> Relation | None:
        """The `peer-cluster` relation that this charm is requiring."""
        return self.model.get_relation(PEER_CLUSTER_RELATION)

    @property
    def peer_clusters(self) -> set[PeerCluster]:
        """The state for all related `peer-cluster` applications that this charm is providing for."""
        peer_clusters = set()
        balancer_kwargs: dict[str, Any] = {
            "balancer_username": self.cluster.balancer_username,
            "balancer_password": self.cluster.balancer_password,
            "balancer_uris": self.cluster.balancer_uris,
        }
        for relation in self.peer_cluster_orchestrator_relations:
            if not relation.app or not self.runs_balancer:
                continue

            peer_clusters.add(
                PeerCluster(
                    relation=relation,
                    data_interface=PeerClusterOrchestratorData(self.model, relation.name),
                    **balancer_kwargs,
                )
            )

        return peer_clusters

    # FIXME: will need renaming once we use Kraft as the orchestrator
    # uses the 'already there' BALANCER username now
    # will need to create one independently with Basic HTTP auth + multiple broker apps
    # right now, multiple<->multiple is very brittle
    @property
    def balancer(self) -> PeerCluster:
        """The state for the `peer-cluster-orchestrator` related balancer application."""
        balancer_kwargs: dict[str, Any] = (
            {
                "balancer_username": self.cluster.balancer_username,
                "balancer_password": self.cluster.balancer_password,
                "balancer_uris": self.cluster.balancer_uris,
            }
            if self.runs_balancer
            else {}
        )

        if self.runs_broker:  # must be requiring, initialise with necessary broker data
            return PeerCluster(
                relation=self.peer_cluster_relation,  # if same app, this will be None and OK
                data_interface=PeerClusterData(self.model, PEER_CLUSTER_RELATION),
                broker_username=ADMIN_USER,
                broker_password=self.cluster.internal_user_credentials.get(ADMIN_USER, ""),
                broker_uris=self.bootstrap_server,
                racks=self.racks,
                broker_capacities=self.broker_capacities,
                zk_username=self.zookeeper.username,
                zk_password=self.zookeeper.password,
                zk_uris=self.zookeeper.uris,
                **balancer_kwargs,  # in case of roles=broker,balancer on this app
            )

        else:  # must be roles=balancer only then, only load with necessary balancer data
            return list(self.peer_clusters)[
                0
            ]  # for broker - balancer relation, currently limited to 1

    @property
    def oauth_relation(self) -> Relation | None:
        """The OAuth relation."""
        return self.model.get_relation(OAUTH_REL_NAME)

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
    def zookeeper(self) -> ZooKeeper:
        """The ZooKeeper relation state."""
        return ZooKeeper(
            relation=self.zookeeper_relation,
            data_interface=self.zookeeper_requires_interface,
            local_app=self.cluster.app,
        )

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
                    zookeeper_uris=self.zookeeper.uris,
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
        super_users = set(INTERNAL_USERS)
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
        if self.client_relations or self.runs_balancer or self.peer_cluster_relation:
            enabled_auth.append(self.default_auth)
        if self.oauth_relation:
            enabled_auth.append(AuthMap(self.default_auth.protocol, "OAUTHBEARER"))
        if self.cluster.mtls_enabled:
            enabled_auth.append(AuthMap("SSL", "SSL"))

        return enabled_auth

    @property
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
            return self.bootstrap_servers_external

        return ",".join(
            sorted(
                [
                    f"{broker.internal_address}:{SECURITY_PROTOCOL_PORTS[self.default_auth].client}"
                    for broker in self.brokers
                ]
            )
        )

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
    def broker_capacities(self) -> dict[str, list[JSON]]:
        """The capacities for all Kafka broker."""
        broker_capacities = []
        for broker in sorted(self.brokers, key=lambda broker: broker.unit_id, reverse=True):
            if not all([broker.cores, broker.storages]):
                return {}

            broker_capacities.append(
                {
                    "brokerId": str(broker.unit_id),
                    "capacity": {
                        "DISK": broker.storages,
                        "CPU": {"num.cores": broker.cores},
                        "NW_IN": str(self.network_bandwidth),
                        "NW_OUT": str(self.network_bandwidth),
                    },
                    "doc": str(broker.host),
                }
            )

        return {"brokerCapacities": broker_capacities}

    @property
    def ready_to_start(self) -> Status:  # noqa: C901
        """Check for active ZooKeeper relation and adding of inter-broker auth username.

        Returns:
            True if ZK is related and `sync` user has been added. False otherwise.
        """
        if not self.peer_relation:
            return Status.NO_PEER_RELATION

        for status in [self._broker_status, self._balancer_status]:
            if status != Status.ACTIVE:
                return status

        return Status.ACTIVE

    @property
    def _balancer_status(self) -> Status:
        """Checks for role=balancer specific readiness."""
        if not self.runs_balancer or not self.unit_broker.unit.is_leader():
            return Status.ACTIVE

        if not self.peer_cluster_orchestrator_relations and not self.runs_broker:
            return Status.NO_PEER_CLUSTER_RELATION

        if not self.balancer.broker_connected:
            return Status.NO_BROKER_DATA

        if len(self.balancer.broker_capacities.get("brokerCapacities", [])) < MIN_REPLICAS:
            return Status.NOT_ENOUGH_BROKERS

        return Status.ACTIVE

    @property
    def _broker_status(self) -> Status:
        """Checks for role=broker specific readiness."""
        if not self.runs_broker:
            return Status.ACTIVE

        if not self.zookeeper:
            return Status.ZK_NOT_RELATED

        if not self.zookeeper.zookeeper_connected:
            return Status.ZK_NO_DATA

        # TLS must be enabled for Kafka and ZK or disabled for both
        if self.cluster.tls_enabled ^ self.zookeeper.tls:
            return Status.ZK_TLS_MISMATCH

        if self.cluster.tls_enabled and not self.unit_broker.certificate:
            return Status.NO_CERT

        if not self.cluster.internal_user_credentials:
            return Status.NO_BROKER_CREDS

        return Status.ACTIVE

    @property
    def runs_balancer(self) -> bool:
        """Is the charm enabling the balancer?"""
        return BALANCER.value in self.roles

    @property
    def runs_broker(self) -> bool:
        """Is the charm enabling the broker(s)?"""
        return BROKER.value in self.roles
