#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""KafkaProvider class and methods."""

import json
import logging
from typing import TYPE_CHECKING

from charms.data_platform_libs.v0.data_interfaces import (
    PROV_SECRET_PREFIX,
    REQ_SECRET_FIELDS,
    CachedSecret,
    Data,
    diff,
    set_encoded_field,
)
from ops.charm import (
    RelationBrokenEvent,
    RelationChangedEvent,
    RelationCreatedEvent,
    RelationEvent,
    SecretChangedEvent,
)
from ops.framework import Object

from core.cluster import custom_secret_groups
from literals import (
    BALANCER,
    BROKER,
    CONTROLLER,
    PEER_CLUSTER_ORCHESTRATOR_RELATION,
    PEER_CLUSTER_RELATION,
)

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)


class PeerClusterEventsHandler(Object):
    """Implements the broker provider-side logic for peer-cluster relations."""

    def __init__(self, charm: "KafkaCharm") -> None:
        super().__init__(charm, "peer_cluster")
        self.charm: "KafkaCharm" = charm

        self.framework.observe(
            self.charm.on.secret_changed,
            self._on_secret_changed_event,
        )

        for relation_name in [PEER_CLUSTER_RELATION, PEER_CLUSTER_ORCHESTRATOR_RELATION]:
            self.framework.observe(
                self.charm.on[relation_name].relation_created,
                self._on_peer_cluster_created,
            )

        self.framework.observe(
            self.charm.on[PEER_CLUSTER_RELATION].relation_changed, self._on_peer_cluster_changed
        )
        self.framework.observe(
            self.charm.on[PEER_CLUSTER_ORCHESTRATOR_RELATION].relation_changed,
            self._on_peer_cluster_orchestrator_changed,
        )

        # ensures data updates, eventually
        self.framework.observe(
            getattr(self.charm.on, "update_status"), self._on_peer_cluster_orchestrator_changed
        )

    def _on_secret_changed_event(self, _: SecretChangedEvent) -> None:
        pass

    def _on_peer_cluster_created(self, event: RelationCreatedEvent) -> None:
        """Generic handler for peer-cluster `relation-created` events."""
        if not self.charm.unit.is_leader() or not event.relation.app:
            return

        requested_secrets = set()
        if self.charm.state.runs_balancer:
            requested_secrets |= set(BALANCER.requested_secrets)
        if self.charm.state.runs_controller:
            requested_secrets |= set(CONTROLLER.requested_secrets)
        if self.charm.state.runs_broker:
            requested_secrets |= set(BROKER.requested_secrets)

        # request secrets for the relation
        set_encoded_field(
            event.relation,
            self.charm.state.cluster.app,
            REQ_SECRET_FIELDS,
            list(requested_secrets),
        )

        # explicitly update the roles early, as we can't determine which model to instantiate
        # until both applications have roles set
        event.relation.data[self.charm.state.cluster.app].update({"roles": self.charm.state.roles})

    def _on_peer_cluster_changed(self, event: RelationChangedEvent) -> None:
        """Generic handler for peer-cluster `relation-changed` events."""
        # ensures secrets have set-up before writing
        if not self.charm.unit.is_leader() or not self.charm.state.peer_cluster.roles:
            return

        self._default_relation_changed(event)

        # will no-op if relation does not exist
        self.charm.state.peer_cluster.update(
            {
                "balancer-username": self.charm.state.peer_cluster.balancer_username,
                "balancer-password": self.charm.state.peer_cluster.balancer_password,
                "balancer-uris": self.charm.state.peer_cluster.balancer_uris,
                "controller-password": self.charm.state.peer_cluster.controller_password,
                "bootstrap-controller": self.charm.state.peer_cluster.bootstrap_controller,
                "bootstrap-unit-id": self.charm.state.peer_cluster.bootstrap_unit_id,
                "bootstrap-replica-id": self.charm.state.peer_cluster.bootstrap_replica_id,
            }
        )

        self.charm.on.config_changed.emit()  # ensure both broker+balancer get a changed event

    def _on_peer_cluster_orchestrator_changed(self, event: RelationChangedEvent) -> None:
        """Generic handler for peer-cluster-orchestrator `relation-changed` events."""
        # TODO: `cluster_manager` check instead of runs_broker
        if (
            not self.charm.unit.is_leader()
            or not self.charm.state.runs_broker  # only broker needs handle this event
            or not any(
                role in self.charm.state.peer_cluster.roles
                for role in [BALANCER.value, CONTROLLER.value]
            )  # ensures secrets have set-up before writing, and only writing to controller,balancers
        ):
            return

        self._default_relation_changed(event)

        # will no-op if relation does not exist
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

        self.charm.on.config_changed.emit()  # ensure both broker+balancer get a changed event

    def _on_peer_cluster_broken(self, _: RelationBrokenEvent):
        """Handle the required logic to remove."""
        if self.charm.state.kraft_mode is not None:
            return

        self.charm.workload.stop()
        logger.info(f'Service {self.model.unit.name.split("/")[1]} stopped')

        # FIXME: probably a mix between cluster_manager and broker
        if self.charm.state.runs_broker:
            # Kafka keeps a meta.properties in every log.dir with a unique ClusterID
            # this ID is provided by ZK, and removing it on relation-broken allows
            # re-joining to another ZK cluster.
            for storage in self.charm.model.storages["data"]:
                self.charm.workload.exec(
                    [
                        "rm",
                        f"{storage.location}/meta.properties",
                        f"{storage.location}/__cluster_metadata-0/quorum-state",
                    ]
                )

            if self.charm.unit.is_leader():
                # other charm methods assume credentials == ACLs
                # necessary to clean-up credentials once ZK relation is lost
                for username in self.charm.state.cluster.internal_user_credentials:
                    self.charm.state.cluster.update({f"{username}-password": ""})

    def _default_relation_changed(self, event: RelationChangedEvent):
        """Implements required logic from multiple 'handled' events from the `data-interfaces` library."""
        if not isinstance(event, RelationEvent) or not event.relation or not event.relation.app:
            return

        diff_data = diff(event, self.charm.state.cluster.app)

        if any(newval for newval in diff_data.added if newval.startswith(PROV_SECRET_PREFIX)):
            for group in custom_secret_groups.groups():
                secret_field = f"{PROV_SECRET_PREFIX}{group}"
                if secret_field in diff_data.added and (
                    secret_uri := event.relation.data[event.relation.app].get(secret_field)
                ):
                    label = Data._generate_secret_label(
                        event.relation.name, event.relation.id, group
                    )
                    CachedSecret(
                        self.charm.model, self.charm.state.cluster.app, label, secret_uri
                    ).meta
