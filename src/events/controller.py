#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Handler for controller specific logic."""

import logging
from typing import TYPE_CHECKING

from ops import (
    LeaderElectedEvent,
    Object,
    PebbleReadyEvent,
    RelationDepartedEvent,
    StartEvent,
    UpdateStatusEvent,
)

from literals import (
    CONTAINER,
    CONTROLLER,
    INTERNAL_USERS,
    PEER,
    Status,
)
from managers.controller import ControllerManager
from workload import KafkaWorkload

if TYPE_CHECKING:
    from charm import KafkaCharm
    from events.broker import BrokerOperator

logger = logging.getLogger(__name__)


class KRaftHandler(Object):
    """Handler for KRaft specific events."""

    def __init__(self, broker: "BrokerOperator") -> None:
        super().__init__(broker, CONTROLLER.value)
        self.charm: "KafkaCharm" = broker.charm
        self.broker: "BrokerOperator" = broker

        self.workload = KafkaWorkload(
            container=(
                self.charm.unit.get_container(CONTAINER) if self.charm.substrate == "k8s" else None
            )
        )

        self.controller_manager = ControllerManager(self.charm.state, self.workload)

        self.upgrade = self.broker.upgrade

        self.framework.observe(getattr(self.charm.on, "start"), self._on_start)
        self.framework.observe(getattr(self.charm.on, "leader_elected"), self._leader_elected)

        if self.charm.substrate == "k8s":
            self.framework.observe(getattr(self.charm.on, "kafka_pebble_ready"), self._on_start)

        self.framework.observe(getattr(self.charm.on, "update_status"), self._on_update_status)

        self.framework.observe(
            self.charm.on[PEER].relation_departed, self._on_peer_relation_departed
        )

    def _on_start(self, event: StartEvent | PebbleReadyEvent) -> None:  # noqa: C901
        """Handler for `start` or `pebble-ready` events."""
        if not self.workload.container_can_connect:
            event.defer()
            return

        # don't want to run default start/pebble-ready events during upgrades
        if not self.upgrade.idle:
            return

        self._init_kraft_mode()

        current_status = self.charm.state.ready_to_start
        if current_status is not Status.ACTIVE:
            event.defer()
            return

        self._format_storages()

        # update status to add controller
        self.charm.on.update_status.emit()

    def _on_update_status(self, _: UpdateStatusEvent) -> None:
        """Handler for `update-status` events."""
        if not self.upgrade.idle or not self.broker.healthy:
            return

        self.add_to_quorum()

    def _init_kraft_mode(self) -> None:
        """Initialize the server when running controller mode."""
        # NOTE: checks for `runs_broker` in this method should be `is_cluster_manager` in
        # the large deployment feature.
        if not self.model.unit.is_leader() or not self.charm.state.kraft_mode:
            return

        if not self.charm.state.cluster.internal_user_credentials and self.charm.state.runs_broker:
            credentials = [
                (username, self.charm.workload.generate_password()) for username in INTERNAL_USERS
            ]
            for username, password in credentials:
                self.charm.state.cluster.update({f"{username}-password": password})

        # cluster-uuid is only created on the broker (`cluster-manager` in large deployments)
        if not self.charm.state.cluster.cluster_uuid and self.charm.state.runs_broker:
            uuid = self.controller_manager.generate_uuid()
            self.charm.state.cluster.update({"cluster-uuid": uuid})
            self.charm.state.peer_cluster.update({"cluster-uuid": uuid})

        # Controller is tasked with populating quorum bootstrap config
        if self.charm.state.runs_controller and not self.charm.state.cluster.bootstrap_controller:

            generated_password = self.charm.workload.generate_password()

            if self.charm.state.peer_cluster_orchestrator:

                if not self.charm.state.peer_cluster_orchestrator.controller_password:
                    self.charm.state.peer_cluster_orchestrator.update(
                        {"controller-password": generated_password}
                    )
            elif not self.charm.state.peer_cluster.controller_password:
                # single mode, controller & leader
                self.charm.state.cluster.update({"controller-password": generated_password})

            bootstrap_data = {
                "bootstrap-controller": self.charm.state.bootstrap_controller,
                "bootstrap-unit-id": str(self.charm.state.kraft_unit_id),
                "bootstrap-replica-id": self.controller_manager.generate_uuid(),
            }
            self.charm.state.cluster.update(bootstrap_data)

    def _format_storages(self) -> None:
        """Format storages provided relevant keys exist."""
        if not self.charm.state.kraft_mode:
            return

        self.broker.config_manager.set_server_properties()
        if self.charm.state.runs_broker:
            credentials = self.charm.state.cluster.internal_user_credentials
        elif self.charm.state.runs_controller:
            credentials = {
                self.charm.state.peer_cluster.broker_username: self.charm.state.peer_cluster.broker_password
            }

        self.controller_manager.format_storages(
            uuid=self.charm.state.peer_cluster.cluster_uuid,
            internal_user_credentials=credentials,
            initial_controllers=f"{self.charm.state.peer_cluster.bootstrap_unit_id}@{self.charm.state.peer_cluster.bootstrap_controller}:{self.charm.state.peer_cluster.bootstrap_replica_id}",
        )

    def _leader_elected(self, event: LeaderElectedEvent) -> None:
        if (
            not self.charm.state.cluster.bootstrap_controller
            or not self.charm.state.runs_controller
        ):
            return

        updated_bootstrap_data = {
            "bootstrap-controller": self.charm.state.bootstrap_controller,
            "bootstrap-unit-id": str(self.charm.state.kraft_unit_id),
            "bootstrap-replica-id": self.charm.state.unit_broker.directory_id,
        }
        self.charm.state.cluster.update(updated_bootstrap_data)

        if self.charm.state.peer_cluster_orchestrator:
            self.charm.state.peer_cluster_orchestrator.update(updated_bootstrap_data)

        # change bootstrap controller config on followers and brokers
        self.charm.on.config_changed.emit()

    def add_to_quorum(self) -> None:
        """Adds current unit to the dynamic quorum in KRaft mode if this is a follower unit."""
        if (
            self.charm.unit.is_leader()
            or self.charm.state.unit_broker.added_to_quorum
            or not self.charm.state.runs_controller
        ):
            return

        directory_id = self.controller_manager.add_controller(
            self.charm.state.cluster.bootstrap_controller
        )

        self.charm.state.unit_broker.update(
            {"directory-id": directory_id, "added-to-quorum": "true"}
        )

    def remove_from_quorum(self) -> None:
        """Removes current unit from the dynamic quorum in KRaft mode."""
        if not self.charm.state.runs_controller:
            return

        if self.charm.state.unit_broker.added_to_quorum or self.charm.unit.is_leader():
            directory_id = (
                self.charm.state.unit_broker.directory_id
                if not self.charm.unit.is_leader()
                else self.charm.state.cluster.bootstrap_replica_id
            )
            self.charm.state.unit_broker.update({"added-to-quorum": ""})
            self.controller_manager.remove_controller(
                self.charm.state.kraft_unit_id,
                directory_id,
                bootstrap_node=self.charm.state.bootstrap_controller,
            )

    def _on_peer_relation_departed(self, event: RelationDepartedEvent) -> None:
        if event.departing_unit == self.charm.unit:
            self.remove_from_quorum()
