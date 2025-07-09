#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka TLS configuration."""

import base64
import json
import logging
import re
from typing import TYPE_CHECKING

from charms.certificate_transfer_interface.v1.certificate_transfer import (
    CertificatesAvailableEvent,
    CertificatesRemovedEvent,
    CertificateTransferRequires,
)
from charms.tls_certificates_interface.v4.tls_certificates import (
    CertificateAvailableEvent,
    CertificateRequestAttributes,
    PrivateKey,
    TLSCertificatesRequiresV4,
    generate_private_key,
)
from ops.charm import (
    ActionEvent,
    RelationBrokenEvent,
    RelationCreatedEvent,
)
from ops.framework import EventBase, EventSource, Object

from core.models import TLSState
from literals import (
    CERTIFICATE_TRANSFER_RELATION,
    INTERNAL_TLS_RELATION,
    TLS_RELATION,
    Status,
    TLSScope,
)

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)


class RefreshTLSCertificatesEvent(EventBase):
    """Event for refreshing TLS certificates."""


class TLSHandler(Object):
    """Handler for managing the client and unit TLS keys/certs."""

    refresh_tls_certificates = EventSource(RefreshTLSCertificatesEvent)

    def __init__(self, charm: "KafkaCharm") -> None:
        super().__init__(charm, "tls")
        self.charm: "KafkaCharm" = charm

        self.sans = self.charm.broker.tls_manager.build_sans()
        self.common_name = f"{self.charm.unit.name}-{self.charm.model.uuid}"

        peer_private_key = None
        client_private_key = None

        if peer_key := self.charm.state.unit_broker.peer_certs.private_key:
            peer_private_key = PrivateKey.from_string(peer_key)

        if client_key := self.charm.state.unit_broker.client_certs.private_key:
            client_private_key = PrivateKey.from_string(client_key)

        self.certificates = TLSCertificatesRequiresV4(
            self.charm,
            TLS_RELATION,
            certificate_requests=[
                CertificateRequestAttributes(
                    common_name=self.common_name,
                    sans_ip=frozenset(self.sans["sans_ip"]),
                    sans_dns=frozenset(self.sans["sans_dns"]),
                ),
            ],
            refresh_events=[self.refresh_tls_certificates],
            private_key=client_private_key,
        )

        self.peer_certificates = TLSCertificatesRequiresV4(
            self.charm,
            INTERNAL_TLS_RELATION,
            certificate_requests=[
                CertificateRequestAttributes(
                    common_name=self.common_name,
                    sans_ip=frozenset(self.sans["sans_ip"]),
                    sans_dns=frozenset(self.sans["sans_dns"]),
                ),
            ],
            private_key=peer_private_key,
        )

        self._init_credentials()

        for rel in (TLS_RELATION, INTERNAL_TLS_RELATION):
            self.framework.observe(self.charm.on[rel].relation_created, self._tls_relation_created)
            self.framework.observe(self.charm.on[rel].relation_broken, self._tls_relation_broken)

        self.framework.observe(
            getattr(self.certificates.on, "certificate_available"),
            self._on_client_certificate_available,
        )
        self.framework.observe(
            getattr(self.peer_certificates.on, "certificate_available"),
            self._on_peer_certificate_available,
        )

        self.framework.observe(
            getattr(self.charm.on, "set_tls_private_key_action"), self._set_tls_private_key
        )

        self.certificate_transfer = CertificateTransferRequires(
            self.charm, CERTIFICATE_TRANSFER_RELATION
        )
        self.framework.observe(
            self.certificate_transfer.on.certificate_set_updated,
            self._on_mtls_client_certificates_available,
        )
        self.framework.observe(
            self.certificate_transfer.on.certificates_removed,
            self._on_mtls_client_certificates_removed,
        )

    def requirer_state(self, requirer: TLSCertificatesRequiresV4) -> TLSState:
        """Returns the appropriate TLSState based on the scope of the TLS Certificates Requirer instance."""
        if requirer.relationship_name == TLS_RELATION:
            return self.charm.state.unit_broker.client_certs
        elif requirer.relationship_name == INTERNAL_TLS_RELATION:
            return self.charm.state.unit_broker.peer_certs

        raise NotImplementedError(f"{requirer.relationship_name} not supported!")

    def _init_credentials(self) -> None:
        """Sets private key, keystore password and truststore passwords if not already set."""
        for requirer in (self.certificates, self.peer_certificates):
            _, private_key = requirer.get_assigned_certificate(requirer.certificate_requests[0])

            if private_key and self.requirer_state(requirer).private_key != private_key:
                self.requirer_state(requirer).private_key = private_key.raw

        # generate unit private key if not already created by action
        if not self.charm.state.unit_broker.keystore_password:
            self.charm.state.unit_broker.update(
                {"keystore-password": self.charm.workload.generate_password()}
            )
        if not self.charm.state.unit_broker.truststore_password:
            self.charm.state.unit_broker.update(
                {"truststore-password": self.charm.workload.generate_password()}
            )

    def _tls_relation_created(self, event: RelationCreatedEvent) -> None:
        """Handler for `certificates_relation_created` event."""
        if not self.charm.unit.is_leader() or not self.charm.state.peer_relation:
            return

        if event.relation.name == TLS_RELATION:
            self.charm.state.cluster.update({"tls": "enabled"})

    def _tls_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Handler for `certificates_relation_broken` event."""
        state = (
            self.charm.state.unit_broker.client_certs
            if event.relation.name == TLS_RELATION
            else self.charm.state.unit_broker.peer_certs
        )

        # clear TLS state
        state.csr = ""
        state.certificate = ""
        state.chain = ""
        state.ca = ""

        # remove all existing keystores from the unit so we don't preserve certs
        self.charm.broker.tls_manager.remove_stores(scope=state.scope)
        self.charm.balancer.tls_manager.remove_stores(scope=state.scope)

        if state.scope == TLSScope.PEER:
            # switch back to internal TLS
            self.charm.broker.setup_internal_tls()

            state.rotate = True
            self.charm.on.config_changed.emit()

        if not self.charm.unit.is_leader():
            return

        if state.scope == TLSScope.CLIENT:
            self.charm.state.cluster.update({"tls": ""})

    def _handle_certificate_available_event(
        self, event: CertificateAvailableEvent, requirer: TLSCertificatesRequiresV4
    ) -> None:
        """Handle TLS `certificate_available` event for the given TLS requirer."""
        ca_changed = False
        certificate_changed = False

        state = self.requirer_state(requirer)

        if state.certificate and event.certificate.raw != state.certificate:
            certificate_changed = True

        if state.ca and event.ca.raw != state.ca:
            ca_changed = True

        state.certificate = event.certificate.raw
        state.ca = event.ca.raw
        state.chain = json.dumps([certificate.raw for certificate in event.chain])

        for dependent in ["broker", "balancer"]:
            getattr(self.charm, dependent).tls_manager.remove_stores(scope=state.scope)
            getattr(self.charm, dependent).tls_manager.configure()

        if certificate_changed or ca_changed:
            # this will trigger a restart.
            state.rotate = True

    def _on_peer_certificate_available(self, event: CertificateAvailableEvent) -> None:
        """Handler for `certificate_available` event after provider updates signed certs for peer TLS relation."""
        if not self.ready:
            event.defer()
            return

        self._handle_certificate_available_event(event, self.peer_certificates)
        if self.charm.unit.is_leader():
            # Update peer-cluster CA/chain.
            self.charm.state.peer_cluster_ca = self.charm.state.unit_broker.peer_certs.bundle

        self.charm.on.config_changed.emit()

    def _on_client_certificate_available(self, event: CertificateAvailableEvent) -> None:
        """Handler for `certificate_available` event after provider updates signed certs for client TLS relation."""
        if not self.ready:
            event.defer()
            return

        self._handle_certificate_available_event(event, self.certificates)
        self.update_truststore()
        self.charm.on.config_changed.emit()

    def _set_tls_private_key(self, event: ActionEvent) -> None:
        """Handler for `set_tls_private_key` action."""
        key = event.params.get("internal-key") or generate_private_key().raw
        private_key = (
            key
            if re.match(r"(-+(BEGIN|END) [A-Z ]+-+)", key)
            else base64.b64decode(key).decode("utf-8")
        )

        self.charm.state.unit_broker.client_certs.private_key = private_key
        self.certificates._private_key = PrivateKey.from_string(private_key)
        self.refresh_tls_certificates.emit()

    def _on_mtls_client_certificates_available(self, event: CertificatesAvailableEvent) -> None:
        """Handle the certificates available event on the `certifcate_transfer` interface."""
        relation = self.charm.model.get_relation(CERTIFICATE_TRANSFER_RELATION, event.relation_id)
        if not relation or not relation.active:
            return

        if not all(
            [
                self.charm.state.cluster.tls_enabled,
                self.charm.state.unit_broker.client_certs.certificate,
            ]
        ):
            logger.debug("Missing TLS relation, deferring")
            self.charm._set_status(Status.NO_CERT)
            event.defer()
            return

        transferred_certs = self.certificate_transfer.get_all_certificates()

        if (
            self.charm.unit.is_leader()
            and transferred_certs
            and not self.charm.state.cluster.mtls_enabled
        ):
            # Create a "mtls" flag so a new listener (CLIENT_SSL) is created
            self.charm.state.cluster.update({"mtls": "enabled"})
            self.charm.on.config_changed.emit()

        self.update_truststore()

    def _on_mtls_client_certificates_removed(self, event: CertificatesRemovedEvent) -> None:
        """Handle the certificates removed event."""
        self.update_truststore()
        # Turn off MTLS if no clients are remaining.
        if self.charm.unit.is_leader() and not self.charm.state.has_mtls_clients:
            self.charm.state.cluster.update({"mtls": ""})

    def update_truststore(self) -> None:
        """Updates the truststore based on current state of MTLS client relations and certificates available on the `certificate_transfer` interface."""
        if not all(
            [
                self.charm.workload.installed,
                self.charm.state.cluster.tls_enabled,
                self.charm.state.unit_broker.client_certs.certificate,
                self.charm.state.unit_broker.client_certs.ca,
            ]
        ):
            # not ready yet.
            return

        should_reload = False
        live_aliases = set()

        # Client MTLS certs
        for client in self.charm.state.clients:
            if not client.relation:
                continue

            alias = client.alias
            if not self.charm.broker.tls_manager.alias_needs_update(alias, client.mtls_cert):
                continue

            self.charm.broker.tls_manager.update_cert(alias=alias, cert=client.mtls_cert)
            live_aliases.add(alias)
            should_reload = True

        # Transferred certs
        transferred_certs = self.certificate_transfer.get_all_certificates()
        for cert in transferred_certs:
            alias = self.charm.broker.tls_manager.certificate_distinguished_name(cert)
            live_aliases.add(alias)

            if not self.charm.broker.tls_manager.alias_needs_update(alias, cert):
                continue

            self.charm.broker.tls_manager.update_cert(alias=alias, cert=cert)
            should_reload = True

        logger.debug(f"Following aliases should be in the truststore: {live_aliases}")
        if should_reload:
            self.charm.broker.tls_manager.reload_truststore()

    @property
    def ready(self) -> bool:
        """Returns True if workload and peer relation is ready, False otherwise."""
        if not all([self.charm.workload.container_can_connect, self.charm.workload.installed]):
            logger.debug("Workload not ready yet.")
            return False

        if not self.charm.state.peer_relation:
            logger.warning("No peer relation on certificate available.")
            return False

        return True
