#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""KafkaProvider class and methods."""

import logging
import subprocess  # nosec B404
from typing import TYPE_CHECKING

from charms.data_platform_libs.v0.data_interfaces import (
    KafkaClientMtlsCertUpdatedEvent,
    KafkaProviderEventHandlers,
    TopicRequestedEvent,
)
from ops.charm import RelationBrokenEvent, RelationCreatedEvent
from ops.framework import Object
from ops.pebble import ExecError

from core.models import KafkaClient
from literals import REL_NAME, Status
from managers.ssl_principal_mapper import NoMatchingRuleError, SslPrincipalMapper

if TYPE_CHECKING:
    from charm import KafkaCharm
    from events.broker import BrokerOperator

logger = logging.getLogger(__name__)


class KafkaProvider(Object):
    """Implements the provider-side logic for client applications relating to Kafka."""

    def __init__(self, dependent: "BrokerOperator") -> None:
        super().__init__(dependent, "kafka_client")
        self.dependent = dependent
        self.charm: "KafkaCharm" = dependent.charm

        self.ssl_principal_mapper = SslPrincipalMapper(
            self.charm.config.ssl_principal_mapping_rules
        )

        self.kafka_provider = KafkaProviderEventHandlers(
            self.charm, self.charm.state.client_provider_interface
        )

        self.framework.observe(self.charm.on[REL_NAME].relation_created, self._on_relation_created)
        self.framework.observe(self.charm.on[REL_NAME].relation_broken, self._on_relation_broken)

        self.framework.observe(
            getattr(self.kafka_provider.on, "topic_requested"), self.on_topic_requested
        )
        self.framework.observe(
            getattr(self.kafka_provider.on, "mtls_cert_updated"), self.on_mtls_cert_updated
        )

    def on_topic_requested(self, event: TopicRequestedEvent):
        """Handle the on topic requested event."""
        if not self.dependent.healthy:
            event.defer()
            return

        if not self.charm.workload.ping(self.charm.state.bootstrap_server_internal):
            logging.debug("Broker/Controller not up yet...")
            event.defer()
            return

        # on all unit update the server properties to enable client listener if needed
        self.dependent._on_config_changed(event)

        if not self.charm.unit.is_leader() or not self.charm.state.peer_relation:
            return

        requesting_client = None
        for client in self.charm.state.clients:
            if event.relation == client.relation:
                requesting_client = client
                break

        if not requesting_client:
            event.defer()
            return

        # We don't want to set credentials for the client before MTLS setup.
        if requesting_client.mtls_cert and not all(
            [
                self.charm.state.cluster.tls_enabled,
                self.charm.state.unit_broker.client_certs.certificate,
            ]
        ):
            logger.debug("Missing TLS relation, deferring")
            self.charm._set_status(Status.MTLS_REQUIRES_TLS)
            event.defer()
            return

        if requesting_client.mtls_cert and self.dependent.tls_manager.alias_needs_update(
            requesting_client.alias, requesting_client.mtls_cert
        ):
            logging.debug("Waiting for MTLS setup.")
            event.defer()
            return

        password = client.password or self.charm.workload.generate_password()

        # catching error here in case listeners not established for bootstrap-server auth
        try:
            self.dependent.auth_manager.add_user(
                username=client.username,
                password=password,
            )
        except (subprocess.CalledProcessError, ExecError):
            logger.warning(f"unable to create user {client.username} just yet")
            event.defer()
            return

        # non-leader units need cluster_config_changed event to update their super.users
        self.charm.state.cluster.update({client.username: password})

        self.dependent.auth_manager.update_user_acls(
            username=client.username,
            topic=client.topic,
            extra_user_roles=client.extra_user_roles,
            group=client.consumer_group_prefix,
        )

        # non-leader units need cluster_config_changed event to update their super.users
        self.charm.state.cluster.update({"super-users": self.charm.state.super_users})

        self.dependent.update_client_data()

    def on_mtls_cert_updated(self, event: KafkaClientMtlsCertUpdatedEvent) -> None:
        """Handler for `kafka-client-mtls-cert-updated` event."""
        if not self.charm.broker.healthy:
            event.defer()
            return

        if not event.mtls_cert:
            logger.info("No MTLS cert provided. skipping MTLS setup.")
            return

        if not event.relation or not event.relation.active:
            return

        if not all(
            [
                self.charm.state.cluster.tls_enabled,
                self.charm.state.unit_broker.client_certs.certificate,
            ]
        ):
            logger.debug("Missing TLS relation, deferring")
            self.charm._set_status(Status.MTLS_REQUIRES_TLS)
            event.defer()
            return

        # check for leaf certificate condition
        if not self.dependent.tls_manager.is_valid_leaf_certificate(event.mtls_cert):
            self.charm._set_status(Status.INVALID_CLIENT_CERTIFICATE)
            return

        if self.charm.unit.is_leader() and not self.charm.state.cluster.mtls_enabled:
            # Create a "mtls" flag so a new listener (CLIENT_SSL) is created
            self.charm.state.cluster.update({"mtls": "enabled"})
            self.charm.on.config_changed.emit()

        if not self.charm.workload.ping(self.charm.state.bootstrap_server_internal):
            logging.debug("Broker/Controller not up yet...")
            event.defer()
            return

        distinguished_name = self.dependent.tls_manager.certificate_distinguished_name(
            event.mtls_cert
        )
        try:
            cert_principal = self.ssl_principal_mapper.get_name(
                distinguished_name=distinguished_name
            )
        except NoMatchingRuleError:
            logger.error(
                f"Relation {event.relation.id} doesn't have a certificate that can be mapped to the current ssl_principal_mapping_rules"
            )
            return

        client = next(
            iter(
                [
                    client
                    for client in self.charm.state.clients
                    if client.relation == event.relation
                ]
            )
        )
        self.dependent.auth_manager.remove_all_user_acls(client.username)
        self.dependent.auth_manager.update_user_acls(
            username=cert_principal,
            topic=client.topic,
            extra_user_roles=client.extra_user_roles,
            group=client.consumer_group_prefix,
        )

        self.charm.tls.update_truststore()

    def _on_relation_created(self, event: RelationCreatedEvent) -> None:
        """Handler for `kafka-client-relation-created` event."""
        self.dependent._on_config_changed(event)

    def _on_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Handler for `kafka-client-relation-broken` event.

        Removes relation users from cluster.

        Args:
            event: the event from a related client application needing a user
        """
        if not self.dependent.healthy:
            event.defer()
            return

        # All units will need to remove the MTLS cert (if any) from their truststores, if the client relation is ACTUALLY broken.
        alias = KafkaClient.generate_alias(
            app_name=event.relation.app.name,
            relation_id=event.relation.id,
        )
        if (
            alias in self.dependent.tls_manager.trusted_certificates
            and event.relation.app != self.charm.app
        ):
            # Remove ACLs on leader
            if self.charm.unit.is_leader():
                username = self.dependent.tls_manager.alias_common_name(alias=alias)
                self.dependent.auth_manager.remove_all_user_acls(username=username)
            # Then remove the cert on all units
            logger.info(f"Removing {alias=} from truststore...")
            self.dependent.tls_manager.remove_cert(alias=alias)
            self.dependent.tls_manager.reload_truststore()

        if (
            # don't remove anything if app is going down
            self.charm.app.planned_units() == 0
            or not self.charm.unit.is_leader()
            or not self.charm.state.cluster
        ):
            return

        # Turn off MTLS if no clients are remaining.
        if not self.charm.state.has_mtls_clients:
            self.charm.state.cluster.update({"mtls": ""})

        if event.relation.app != self.charm.app or not self.charm.app.planned_units() == 0:
            username = f"relation-{event.relation.id}"

            self.dependent.auth_manager.remove_all_user_acls(username=username)
            self.dependent.auth_manager.delete_user(username=username)

            # non-leader units need cluster_config_changed event to update their super.users
            # update on the peer relation data will trigger an update of server properties on all units
            self.charm.state.cluster.update({username: ""})

        self.dependent.update_client_data()
