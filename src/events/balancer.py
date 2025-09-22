#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Balancer role core charm logic."""

import logging
from subprocess import CalledProcessError
from typing import TYPE_CHECKING, Literal

from ops import (
    ActionEvent,
    CharmEvents,
    EventBase,
    EventSource,
    InstallEvent,
    Object,
)
from ops.pebble import ExecError
from requests import Response

from core.models import RebalanceError, RebalanceEvent
from core.workload import WorkloadBase
from literals import (
    BALANCER,
    BALANCER_WEBSERVER_PORT,
    BALANCER_WEBSERVER_USER,
    CONTAINER,
    MODE_ADD,
    MODE_REMOVE,
    PEER,
    PROFILE_TESTING,
    Status,
)
from managers.balancer import BalancerManager
from managers.config import CRUISE_CONTROL_TESTING_OPTIONS, BalancerConfigManager
from managers.tls import TLSManager
from workload import BalancerWorkload

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)


class BalancerEvents(CharmEvents):
    """Base events for balancer."""

    rebalance = EventSource(RebalanceEvent)


class BalancerOperator(Object):
    """Implements the logic for the balancer."""

    on = BalancerEvents()  # pyright: ignore [reportAssignmentType]

    def __init__(self, charm, kafka_workload: WorkloadBase) -> None:
        super().__init__(charm, BALANCER.value)
        self.charm: "KafkaCharm" = charm
        self.kafka_workload: WorkloadBase = kafka_workload

        self.workload = BalancerWorkload(
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

        # Before fast exit to avoid silently ignoring the action
        self.framework.observe(
            getattr(self.charm.on, "rebalance_action"), self._on_rebalance_action
        )

        # Fast exit after workload instantiation, but before any event observer
        if not self.charm.state.runs_balancer or not self.charm.unit.is_leader():
            return

        self.config_manager = BalancerConfigManager(
            self.charm.state, self.workload, self.charm.config
        )
        self.balancer_manager = BalancerManager(self)

        self.framework.observe(self.charm.on.install, self._on_install)
        self.framework.observe(self.charm.on.start, self._on_start)

        if self.charm.substrate == "k8s":
            self.framework.observe(getattr(self.charm.on, "kafka_pebble_ready"), self._on_start)

        self.framework.observe(self.charm.on.leader_elected, self._on_start)

        # ensures data updates, eventually
        self.framework.observe(self.charm.on.update_status, self._on_config_changed)
        self.framework.observe(self.charm.on.config_changed, self._on_config_changed)
        self.framework.observe(self.charm.on[PEER].relation_changed, self._on_config_changed)

        self.framework.observe(self.on.rebalance, self._on_rebalance_event)

    def _on_install(self, event: InstallEvent) -> None:
        """Handler for `install` event."""
        if not self.workload.container_can_connect:
            event.defer()
            return

        self.config_manager.set_environment()

        if self.charm.config.profile == PROFILE_TESTING:
            logger.info(
                "CruiseControl is deployed with the 'testing' profile."
                "The following properties will be set:\n"
                f"{CRUISE_CONTROL_TESTING_OPTIONS}"
            )

    def _on_start(self, event: EventBase) -> None:
        """Handler for `start` or `pebble-ready` events."""
        current_status = self.charm.state.balancer_status
        if current_status is not Status.ACTIVE:
            self.charm._set_status(current_status)
            return

        if not self.charm.state.cluster.balancer_password:
            payload = {
                "balancer-username": BALANCER_WEBSERVER_USER,
                "balancer-password": self.charm.workload.generate_password(),
                "balancer-uris": f"{self.charm.state.unit_broker.internal_address}:{BALANCER_WEBSERVER_PORT}",
            }
            # Update relation data intra & extra cluster (if it exists)
            self.charm.state.cluster.update(payload)

            if self.charm.state.peer_cluster_orchestrator:
                self.charm.state.peer_cluster_orchestrator.update(payload)

        self.setup_internal_tls()
        self.config_manager.set_cruise_control_properties()
        self.config_manager.set_broker_capacities()
        self.config_manager.set_cruise_control_auth()

        try:
            self.balancer_manager.create_internal_topics()
        except (CalledProcessError, ExecError) as e:
            logger.warning(e.stdout)
            event.defer()
            return

        self.workload.restart()

        if self.charm.state.balancer_tls_rotate:
            self.charm.state.balancer_tls_rotate = False

        logger.info("CruiseControl service started")

    def _on_config_changed(self, _: EventBase) -> None:
        """Generic handler for 'something changed' events."""
        if not self.charm.unit.is_leader():
            return

        if not self.healthy:
            return

        if self.balancer_manager.config_change_detected() or self.charm.state.balancer_tls_rotate:
            # safe to update everything even if it hasn't changed, service will restart anyway
            self.config_manager.set_cruise_control_properties()
            self.config_manager.set_broker_capacities()

            self.charm.on.start.emit()

        # Auto-balance
        if not self.charm.config.auto_balance:
            return

        partition_assignment = self.kafka_workload.get_partition_assignment(
            self.charm.state.bootstrap_server_internal
        )
        for _id, partitions in partition_assignment.items():
            broker_id = int(_id.split("/")[0])
            if not partitions:
                getattr(self.on, "rebalance").emit(
                    self.charm.state.cluster.relation,
                    "add",
                    broker_id,
                    app=self.charm.app,
                    unit=self.charm.unit,
                )

    def _on_rebalance_action(self, event: ActionEvent) -> None:
        """Handle the `rebalance` Juju action."""
        try:
            response = self.rebalance(
                trigger="action",
                mode=event.params["mode"],
                broker_id=event.params.get("brokerid"),
                dryrun=event.params.get("dryrun", True),
            )
        except RebalanceError as e:
            event.set_results({"error": f"{e}"})
            event.fail(f"{e}")
            return

        sanitised_response = self.balancer_manager.clean_results(response.json())
        if not isinstance(sanitised_response, dict):
            event.set_results({"error": "Unknown error"})
            event.fail("Unknown error")
            return

        event.set_results(sanitised_response)

    def _on_rebalance_event(self, event: RebalanceEvent) -> None:
        """Handle the rebalance event."""
        if (
            event.mode == "remove"
            and event.broker_id
            and self.kafka_workload.all_storages_drained(
                self.charm.state.bootstrap_server_internal, event.broker_id
            )
        ):
            # We have nothing to do...
            return

        if any(
            [
                not self.balancer_manager.cruise_control.monitoring,
                self.balancer_manager.cruise_control.executing,
                not self.balancer_manager.cruise_control.ready,
            ]
        ):
            # No need to defer, we'll retry on the next update-status.
            logger.info("Cruise Control not ready yet.")
            return

        logger.debug(f"Reblance event mode={event.mode} broker_id={event.broker_id}")

        try:
            self.rebalance(
                trigger="event", mode=event.mode, broker_id=event.broker_id, dryrun=False
            )
        except RebalanceError as e:
            logger.error(f"{e}")
            event.defer()
            return

        if event.mode == "remove" and event.broker_id:
            self.charm.state.cluster.remove_broker(event.broker_id)

    def rebalance(
        self,
        trigger: Literal["action", "event"],
        mode: str,
        broker_id: int | None,
        dryrun: bool = True,
    ) -> Response:
        """Perform a rebalance using Cruise Control."""
        if self.charm.state.runs_broker:
            available_brokers = [broker.broker_id for broker in self.charm.state.brokers]
        else:
            brokers = (
                [broker.name for broker in self.charm.state.peer_cluster.relation.units]
                if self.charm.state.peer_cluster.relation
                else []
            )
            # FIXME: wrong broker id
            available_brokers = [int(broker.split("/")[1]) for broker in brokers]

        failure_conditions = [
            (
                lambda: not self.charm.state.runs_balancer,
                "Action must be run on an application with balancer role",
            ),
            (
                lambda: not self.charm.unit.is_leader(),
                "Action must be run on the application leader",
            ),
            (
                lambda: not self.balancer_manager.cruise_control.monitoring,
                "CruiseControl balancer service is not yet ready",
            ),
            (
                lambda: self.balancer_manager.cruise_control.executing,
                "CruiseControl balancer service is currently executing a task, please try again later",
            ),
            (
                lambda: not self.balancer_manager.cruise_control.ready,
                "CruiseControl balancer service has not yet collected enough data to provide a partition reallocation proposal",
            ),
            (
                lambda: mode in (MODE_ADD, MODE_REMOVE) and broker_id is None,
                "'add' and 'remove' rebalance action require passing the 'brokerid' parameter",
            ),
            (
                lambda: trigger == "action"
                and mode in (MODE_ADD, MODE_REMOVE)
                and broker_id not in available_brokers,
                "invalid brokerid",
            ),
        ]

        for check, msg in failure_conditions:
            if check():
                logging.error(msg)
                raise RebalanceError(msg)

        response, user_task_id = self.balancer_manager.rebalance(
            mode=mode, brokerid=broker_id, dryrun=dryrun
        )
        logger.debug(f"rebalance - {vars(response)=}")

        if response.status_code != 200 or "errorMessage" in response.json():
            msg = response.json().get("errorMessage", "")
            raise RebalanceError(
                f"'{mode}' rebalance failed with status code {response.status_code} - {msg}"
            )

        self.charm._set_status(Status.WAITING_FOR_REBALANCE)

        self.balancer_manager.wait_for_task(user_task_id)

        return response

    def setup_internal_tls(self) -> None:
        """Generates a self-signed certificate if required and writes all necessary TLS configuration for internal TLS."""
        if self.charm.state.unit_broker.peer_certs.ready:
            self.tls_manager.configure()
            return

        self_signed_cert = self.tls_manager.generate_self_signed_certificate()
        if not self_signed_cert:
            return

        self.charm.state.unit_broker.peer_certs.set_self_signed(self_signed_cert)
        self.tls_manager.configure()

    @property
    def healthy(self) -> bool:
        """Checks and updates various charm lifecycle states.

        Returns:
            True if service is alive and active. Otherwise False
        """
        # needed in case it's called by BrokerOperator in set_client_data
        if not self.charm.state.runs_balancer:
            return True

        current_status = self.charm.state.balancer_status
        if current_status is not Status.ACTIVE:
            self.charm._set_status(current_status)
            return False

        if not self.workload.active() and self.charm.unit.is_leader():
            self.charm._set_status(Status.CC_NOT_RUNNING)
            return False

        return True
