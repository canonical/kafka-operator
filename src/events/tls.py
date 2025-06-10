#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka TLS configuration."""

import base64
import json
import logging
import re
import warnings
from typing import TYPE_CHECKING

from charms.certificate_transfer_interface.v1.certificate_transfer import (
    CertificatesAvailableEvent,
    CertificatesRemovedEvent,
    CertificateTransferRequires,
)
from charms.tls_certificates_interface.v3.tls_certificates import (
    CertificateAvailableEvent,
    TLSCertificatesRequiresV3,
    generate_csr,
    generate_private_key,
)
from ops.charm import (
    ActionEvent,
    RelationJoinedEvent,
)
from ops.framework import Object

from literals import CERTIFICATE_TRANSFER_RELATION, TLS_RELATION, Status

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)


class TLSHandler(Object):
    """Handler for managing the client and unit TLS keys/certs."""

    def __init__(self, charm: "KafkaCharm") -> None:
        super().__init__(charm, "tls")
        self.charm: "KafkaCharm" = charm

        self.certificates = TLSCertificatesRequiresV3(self.charm, TLS_RELATION)

        # Own certificates handlers
        self.framework.observe(
            self.charm.on[TLS_RELATION].relation_created, self._tls_relation_created
        )
        self.framework.observe(
            self.charm.on[TLS_RELATION].relation_joined, self._tls_relation_joined
        )
        self.framework.observe(
            self.charm.on[TLS_RELATION].relation_broken, self._tls_relation_broken
        )
        self.framework.observe(
            getattr(self.certificates.on, "certificate_available"), self._on_certificate_available
        )
        self.framework.observe(
            getattr(self.certificates.on, "certificate_expiring"), self._on_certificate_expiring
        )
        self.framework.observe(
            getattr(self.charm.on, "set_tls_private_key_action"), self._set_tls_private_key
        )

        self.certificate_transfer = CertificateTransferRequires(
            self.charm, CERTIFICATE_TRANSFER_RELATION
        )
        self.framework.observe(
            self.certificate_transfer.on.certificate_set_updated,
            self._on_client_certificates_available,
        )
        self.framework.observe(
            self.certificate_transfer.on.certificates_removed, self._on_client_certificates_removed
        )

    def _tls_relation_created(self, _) -> None:
        """Handler for `certificates_relation_created` event."""
        if not self.charm.unit.is_leader() or not self.charm.state.peer_relation:
            return

        self.charm.state.cluster.update({"tls": "enabled"})

    def _tls_relation_joined(self, event: RelationJoinedEvent) -> None:
        """Handler for `certificates_relation_joined` event."""
        # generate unit private key if not already created by action
        if not self.charm.workload.installed:
            event.defer()
            return

        if not self.charm.state.unit_broker.private_key:
            self.charm.state.unit_broker.update(
                {"private-key": generate_private_key().decode("utf-8")}
            )

        # generate unit private key if not already created by action
        if not self.charm.state.unit_broker.keystore_password:
            self.charm.state.unit_broker.update(
                {"keystore-password": self.charm.workload.generate_password()}
            )
        if not self.charm.state.unit_broker.truststore_password:
            self.charm.state.unit_broker.update(
                {"truststore-password": self.charm.workload.generate_password()}
            )

        self._request_certificate()

    def _tls_relation_broken(self, _) -> None:
        """Handler for `certificates_relation_broken` event."""
        self.charm.state.unit_broker.update(
            {"csr": "", "certificate": "", "ca-cert": "", "chain": ""}
        )

        # remove all existing keystores from the unit so we don't preserve certs
        self.charm.broker.tls_manager.remove_stores()
        self.charm.balancer.tls_manager.remove_stores()

        if not self.charm.unit.is_leader():
            return

        self.charm.state.cluster.update({"tls": ""})

    def _on_certificate_available(self, event: CertificateAvailableEvent) -> None:
        """Handler for `certificates_available` event after provider updates signed certs."""
        if not self.charm.workload.installed:
            event.defer()
            return

        if not self.charm.state.peer_relation:
            logger.warning("No peer relation on certificate available")
            event.defer()
            return

        # avoid setting tls files and restarting
        if event.certificate_signing_request != self.charm.state.unit_broker.csr:
            logger.error("Can't use certificate, found unknown CSR")
            return

        self.charm.state.unit_broker.update(
            {
                "certificate": event.certificate,
                "ca-cert": event.ca,
                "chain": json.dumps(event.chain),
            }
        )

        for dependent in ["broker", "balancer"]:
            getattr(self.charm, dependent).tls_manager.set_server_key()
            getattr(self.charm, dependent).tls_manager.set_ca()
            getattr(self.charm, dependent).tls_manager.set_chain()
            getattr(self.charm, dependent).tls_manager.set_certificate()
            getattr(self.charm, dependent).tls_manager.set_bundle()
            getattr(self.charm, dependent).tls_manager.set_truststore()
            getattr(self.charm, dependent).tls_manager.set_keystore()

        # single-unit Kafka can lose restart events if it loses connection with TLS-enabled ZK
        self.update_truststore()
        self.charm.on.config_changed.emit()

    def _on_certificate_expiring(self, _) -> None:
        """Handler for `certificate_expiring` event."""
        self._request_certificate_renewal()

    def _set_tls_private_key(self, event: ActionEvent) -> None:
        """Handler for `set_tls_private_key` action."""
        key = event.params.get("internal-key") or generate_private_key().decode("utf-8")
        private_key = (
            key
            if re.match(r"(-+(BEGIN|END) [A-Z ]+-+)", key)
            else base64.b64decode(key).decode("utf-8")
        )

        self.charm.state.unit_broker.update({"private-key": private_key})
        self._on_certificate_expiring(event)

    def _request_certificate(self):
        """Generates and submits CSR to provider."""
        if not self.charm.state.unit_broker.private_key or not self.charm.state.peer_relation:
            logger.error("Can't request certificate, missing private key")
            return

        sans = self.charm.broker.tls_manager.build_sans()

        # only warn during certificate creation, not every event if in structured_config
        if self.charm.config.certificate_extra_sans:
            warnings.warn(
                "'certificate_extra_sans' config option is deprecated, use 'extra_listeners' instead",
                DeprecationWarning,
            )

        csr = generate_csr(
            private_key=self.charm.state.unit_broker.private_key.encode("utf-8"),
            subject=self.charm.state.unit_broker.relation_data.get("private-address", ""),
            sans_ip=sans["sans_ip"],
            sans_dns=sans["sans_dns"],
        )
        self.charm.state.unit_broker.update({"csr": csr.decode("utf-8").strip()})

        self.certificates.request_certificate_creation(certificate_signing_request=csr)

    def _request_certificate_renewal(self):
        """Generates and submits new CSR to provider."""
        if (
            not self.charm.state.unit_broker.private_key
            or not self.charm.state.unit_broker.csr
            or not self.charm.state.peer_relation
        ):
            logger.error("Missing unit private key and/or old csr")
            return

        sans = self.charm.broker.tls_manager.build_sans()
        new_csr = generate_csr(
            private_key=self.charm.state.unit_broker.private_key.encode("utf-8"),
            subject=self.charm.state.unit_broker.relation_data.get("private-address", ""),
            sans_ip=sans["sans_ip"],
            sans_dns=sans["sans_dns"],
        )

        self.certificates.request_certificate_renewal(
            old_certificate_signing_request=self.charm.state.unit_broker.csr.encode("utf-8"),
            new_certificate_signing_request=new_csr,
        )

        self.charm.state.unit_broker.update({"csr": new_csr.decode("utf-8").strip()})

    def _on_client_certificates_available(self, event: CertificatesAvailableEvent) -> None:
        """Handle the certificates available event on the `certifcate_transfer` interface."""
        relation = self.charm.model.get_relation(CERTIFICATE_TRANSFER_RELATION, event.relation_id)
        if not relation or not relation.active:
            return

        if not all(
            [self.charm.state.cluster.tls_enabled, self.charm.state.unit_broker.certificate]
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

    def _on_client_certificates_removed(self, event: CertificatesRemovedEvent) -> None:
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
                self.charm.state.unit_broker.certificate,
                self.charm.state.unit_broker.ca,
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
            alias = self.charm.broker.tls_manager.certificate_common_name(cert)
            live_aliases.add(alias)

            if not self.charm.broker.tls_manager.alias_needs_update(alias, cert):
                continue

            self.charm.broker.tls_manager.update_cert(alias=alias, cert=cert)
            should_reload = True

        logger.debug(f"Following aliases should be in the truststore: {live_aliases}")
        if should_reload:
            self.charm.broker.tls_manager.reload_truststore()
