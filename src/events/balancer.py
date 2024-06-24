"""Balancer role core charm logic."""

import logging
from typing import TYPE_CHECKING

from ops import (
    ActiveStatus,
    ConfigChangedEvent,
    LeaderElectedEvent,
    Object,
    StartEvent,
)

from events.registry import BalancerEvents, BalancerStartEvent
from literals import (
    BALANCER,
    BALANCER_TOPICS,
)
from managers.config import BalancerConfigManager
from workload import BalancerWorkload

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)

BALANCER_EVENTS = "balancer-events"


class BalancerOperator(Object):
    """Implements the logic for the balancer."""

    on = BalancerEvents()  # type: ignore

    def __init__(self, charm) -> None:
        super().__init__(charm, BALANCER_EVENTS)
        self.charm: "KafkaCharm" = charm

        if BALANCER.value not in self.charm.config.roles:
            return

        self.workload = BalancerWorkload()
        self.config_manager = BalancerConfigManager(
            self.charm.state, self.workload, self.charm.config
        )

        # self.balancer_requirer = BalancerRequirer(self.charm)

        ## Charm-level events

        self.framework.observe(self.charm.on.install, self._on_install)
        self.framework.observe(self.charm.on.start, self._on_start)
        self.framework.observe(
            self.charm.on[BALANCER.value].relation_changed, self._on_config_changed
        )

        ## Role-level events

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)

    def _on_install(self, _) -> None:
        """Handler for `install` event."""
        self.config_manager.set_environment()

    def _on_start(self, _: StartEvent) -> None:
        """Handler for `start` event."""
        if not self.charm.unit.is_leader():
            self.workload.stop()
            logger.info("Cruise control stopped")
            return

        self.charm._set_status(self.charm.state.ready_to_balance)

        if not isinstance(self.charm.unit.status, ActiveStatus):
            BalancerStartEvent(self.on.handle).defer()
            # balancer_obs.start.defer()
            return

        self.config_manager.set_cruise_control_properties()
        self.config_manager.set_broker_capacities()
        self.config_manager.set_cruise_control_jaas_config()

        self.config_manager.set_environment()
        for topic in BALANCER_TOPICS:
            if topic not in self.workload.run_bin_command(
                "topics",
                [
                    "--list",
                    "--bootstrap-server",
                    f"{self.charm.state.internal_bootstrap_server}",
                    "--command-config",
                    f'{BALANCER.paths["CONF"]}/cruisecontrol.properties',
                ],
                opts=[
                    self.config_manager.kafka_opts,
                ],
            ):
                self.workload.run_bin_command(
                    "topics",
                    [
                        "--create",
                        "--topic",
                        topic,
                        "--bootstrap-server",
                        f"{self.charm.state.internal_bootstrap_server}",
                        "--command-config",
                        f'{BALANCER.paths["CONF"]}/cruisecontrol.properties',
                    ],
                    opts=[
                        self.config_manager.kafka_opts,
                    ],
                )

        logger.error(self.workload.read("/etc/environment"))
        self.workload.start()

        logger.info("Cruise control started")

    def _on_leader_elected(self, event: LeaderElectedEvent) -> None:
        """Handler for `leader-elected` event."""
        if not self.workload.active():
            event.defer()
            return

        self.on.start.emit()

    def _on_config_changed(self, _: ConfigChangedEvent) -> None:
        """Handler for `config-changed` event."""
        self.on.start.emit()


# class BalancerProvider(Object):
#     """Implement the provider-side logic for the balancer."""

#     def __init__(self, charm) -> None:
#         super().__init__(charm, BALANCER_RELATION)
#         self.charm: "KafkaCharm" = charm

#         self.relation_data = self.charm.state.balancer

#         self.provider_handler = KafkaProviderEventHandlers(
#             self.charm,
#             self.relation_data.data_interface,  # pyright: ignore[reportGeneralTypeIssues, reportArgumentType]
#         )

#         self.framework.observe(
#             self.charm.on[BALANCER_RELATION].relation_created, self._on_relation_created
#         )
#         self.framework.observe(
#             self.charm.on[BALANCER_RELATION].relation_broken, self._on_relation_broken
#         )

#         self.framework.observe(
#             getattr(self.provider_handler.on, "topic_requested"), self._on_topic_requested
#         )

#     def _on_relation_created(self, _) -> None:
#         """Handler for `balancer-relation-created` event."""
#         pass

#     def _on_topic_requested(self, event) -> None:
#         """Handler for `topic_requested` event."""
#         if not self.charm.healthy:
#             event.defer()
#             return

#         # on all unit update the server properties to enable balancer listener if needed
#         self.charm._on_config_changed(event)

#         if not self.charm.unit.is_leader() or not self.charm.state.peer_relation:
#             return

#         balancer = self.charm.state.balancer
#         if not balancer:
#             event.defer()
#             return

#         password = balancer.password or self.charm.workload.generate_password()

#         # catching error here in case listeners not established for bootstrap-server auth
#         try:
#             self.charm.auth_manager.add_user(
#                 username=balancer.username,
#                 password=password,
#             )
#         except (subprocess.CalledProcessError, ExecError):
#             logging.exception("")
#             logger.warning(f"unable to create user {balancer.username} just yet")
#             event.defer()
#             return

#         # non-leader units need cluster_config_changed event to update their super.users
#         self.charm.state.cluster.update({balancer.username: password})

#         self.charm.auth_manager.update_user_acls(
#             username=balancer.username,
#             topic=BALANCER_TOPIC,
#             extra_user_roles=ADMIN_USER,
#             group=None,
#         )

#         # non-leader units need cluster_config_changed event to update their super.users
#         self.charm.state.cluster.update({"super-users": self.charm.state.super_users})

#         self.charm.update_client_data()

#     def _on_relation_broken(self, event: RelationBrokenEvent) -> None:
#         """Handler for `balancer-relation-broken` event.

#         Removes balancer user from ZooKeeper.

#         Args:
#             event: the event from a related balancer application
#         """
#         if (
#             # don't remove anything if app is going down
#             self.charm.app.planned_units == 0
#             or not self.charm.unit.is_leader()
#             or not self.charm.state.cluster
#         ):
#             return

#         if not self.charm.healthy:
#             event.defer()
#             return

#         if event.relation.app != self.charm.app or not self.charm.app.planned_units() == 0:
#             username = f"relation-{event.relation.id}"

#             self.charm.auth_manager.remove_all_user_acls(username=username)
#             self.charm.auth_manager.delete_user(username=username)

#             # non-leader units need cluster_config_changed event to update their super.users
#             # update on the peer relation data will trigger an update of server properties on all units
#             self.charm.state.cluster.update({username: ""})

#         self.charm.update_client_data()


# class BalancerRequirerEventHandlers(RequirerEventHandlers):
#     """Override abstract event handlers."""

#     relation_data: BalancerRequirerData

#     def _on_relation_created_event(self, event: RelationCreatedEvent) -> None:
#         """Event emitted when the database relation is created."""
#         super()._on_relation_created_event(event)
#         event_data = {"extra-user-roles": ADMIN_USER, "topic": BALANCER_TOPIC}
#         self.relation_data.update_relation_data(event.relation.id, event_data)

#     def _on_relation_changed_event(self, event: RelationChangedEvent) -> None:
#         # Check which data has changed to emit customs events.
#         diff = self._diff(event)

#         # Register all new secrets with their labels
#         if any(newval for newval in diff.added if self.relation_data._is_secret_field(newval)):
#             self.relation_data._register_secrets_to_relation(event.relation, diff.added)

#     def _on_secret_changed_event(self, _: RelationChangedEvent) -> None:
#         pass


# class BalancerRequirer(Object):
#     """Implement the requirer-side logic for the balancer."""

#     def __init__(self, charm) -> None:
#         super().__init__(charm, BALANCER_SERVICE)
#         self.charm: "KafkaCharm" = charm
#         self.relation_data = self.charm.state.balancer

#         self.requirer_handler = BalancerRequirerEventHandlers(
#             self.charm,
#             self.relation_data.data_interface,  # pyright: ignore[reportGeneralTypeIssues, reportArgumentType]
#             BALANCER_SERVICE,
#         )

#         self.framework.observe(
#             self.charm.on[BALANCER_SERVICE].relation_joined, self._on_relation_changed
#         )
#         self.framework.observe(
#             self.charm.on[BALANCER_SERVICE].relation_changed, self._on_relation_changed
#         )
#         self.framework.observe(
#             self.charm.on[BALANCER_SERVICE].relation_broken, self._on_relation_broken
#         )

#     def _on_relation_changed(self, event) -> None:
#         """Handler for `balancer-relation-created` event."""
#         self.charm.on.config_changed.emit()

#     def _on_relation_broken(self, _) -> None:
#         """Handler for `balancer-relation-created` event."""
#         self.charm.workload.stop()

#         logger.info(f'Balancer {self.model.unit.name.split("/")[1]} stopped')
#         self.charm._set_status(Status.BROKER_NOT_RELATED)
