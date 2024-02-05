#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Objects representing the state of KafkaCharm."""

import os

from ops import Framework, Object, Relation

from core.models import KafkaBroker, KafkaCluster, ZooKeeper
from literals import (
    INTERNAL_USERS,
    PEER,
    REL_NAME,
    SECURITY_PROTOCOL_PORTS,
    ZK,
    Status,
    Substrate,
)


class ClusterState(Object):
    """Properties and relations of the charm."""

    def __init__(self, charm: Framework | Object, substrate: Substrate):
        super().__init__(parent=charm, key="charm_state")
        self.substrate: Substrate = substrate

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

    # --- CORE COMPONENTS ---

    @property
    def broker(self) -> KafkaBroker:
        """The server state of the current running Unit."""
        return KafkaBroker(
            relation=self.peer_relation, component=self.model.unit, substrate=self.substrate
        )

    @property
    def cluster(self) -> KafkaCluster:
        """The cluster state of the current running App."""
        return KafkaCluster(
            relation=self.peer_relation, component=self.model.app, substrate=self.substrate
        )

    @property
    def brokers(self) -> set[KafkaBroker]:
        """Grabs all servers in the current peer relation, including the running unit server.

        Returns:
            Set of KafkaBrokers in the current peer relation, including the running unit server.
        """
        if not self.peer_relation:
            return set()

        servers = set()
        for unit in self.peer_relation.units:
            servers.add(
                KafkaBroker(relation=self.peer_relation, component=unit, substrate=self.substrate)
            )
        servers.add(self.broker)

        return servers

    @property
    def zookeeper(self) -> ZooKeeper:
        """The ZooKeeper relation state."""
        return ZooKeeper(
            relation=self.zookeeper_relation,
            component=self.model.app,
            substrate=self.substrate,
            local_app=self.model.app,
            local_unit=self.model.unit,
        )

    # ---- GENERAL VALUES ----

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
    def port(self) -> int:
        """Return the port to be used internally."""
        return (
            SECURITY_PROTOCOL_PORTS["SASL_SSL"].client
            if (self.cluster.tls_enabled and self.broker.certificate)
            else SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT"].client
        )

    @property
    def bootstrap_server(self) -> list[str]:
        """The current Kafka uris formatted for the `bootstrap-server` command flag.

        Returns:
            List of `bootstrap-server` servers
        """
        if not self.peer_relation:
            return []

        return [f"{host}:{self.port}" for host in self.unit_hosts]

    @property
    def log_dirs(self) -> str:
        """Builds the necessary log.dirs based on mounted storage volumes.

        Returns:
            String of log.dirs property value to be set
        """
        return ",".join([os.fspath(storage.location) for storage in self.model.storages["data"]])

    @property
    def unit_hosts(self) -> list[str]:
        """Return list of application unit hosts."""
        hosts = [broker.host for broker in self.brokers]
        return hosts

    @property
    def planned_units(self) -> int:
        """Return the planned units for the charm."""
        return self.model.app.planned_units()

    @property
    def ready_to_start(self) -> Status:
        """Check for active ZooKeeper relation and adding of inter-broker auth username.

        Returns:
            True if ZK is related and `sync` user has been added. False otherwise.
        """
        if not self.peer_relation:
            return Status.NO_PEER_RELATION

        if not self.zookeeper.zookeeper_related:
            return Status.ZK_NOT_RELATED

        if not self.zookeeper.zookeeper_connected:
            return Status.ZK_NO_DATA

        # TLS must be enabled for Kafka and ZK or disabled for both
        if self.cluster.tls_enabled ^ self.zookeeper.tls:
            return Status.ZK_TLS_MISMATCH

        if not self.cluster.internal_user_credentials:
            return Status.NO_BROKER_CREDS

        return Status.ACTIVE
