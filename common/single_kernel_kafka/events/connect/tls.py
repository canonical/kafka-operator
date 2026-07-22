#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""TLSHandler class and methods."""

import json
import logging
from typing import TYPE_CHECKING

from charms.tls_certificates_interface.v3.tls_certificates import (
    CertificateAvailableEvent,
    TLSCertificatesRequiresV3,
    generate_csr,
    generate_private_key,
)
from ops.framework import Object

from ...core.literals import ConnectLiterals, TLSScope

if TYPE_CHECKING:
    from ...core.connect_models import ConnectCharmBase


logger = logging.getLogger(__name__)


class TLSHandler(Object):
    """Generic Handler for TLS events."""

    def __init__(
        self, charm: "ConnectCharmBase", relation_name: str = ConnectLiterals.TLS_REL
    ) -> None:
        super().__init__(charm, f"tls-{relation_name}")

        self.charm = charm
        self.tls_rel = relation_name
        self.unit_tls_context = charm.context.worker_unit.tls
        self.certificates = TLSCertificatesRequiresV3(charm, self.tls_rel)

        self.framework.observe(
            self.charm.on[self.tls_rel].relation_created, self._tls_relation_created
        )
        self.framework.observe(
            self.charm.on[self.tls_rel].relation_joined, self._tls_relation_joined
        )
        self.framework.observe(
            self.charm.on[self.tls_rel].relation_broken, self._tls_relation_broken
        )

        self.framework.observe(
            getattr(self.certificates.on, "certificate_available"), self._on_certificate_available
        )
        self.framework.observe(
            getattr(self.certificates.on, "certificate_expiring"), self._on_certificate_expiring
        )

    def _tls_relation_created(self, _) -> None:
        """Handler for `certificates_relation_created` event."""
        if not self.charm.unit.is_leader() or not self.charm.context.peer_workers:
            return

        self.charm.context.peer_workers.update({"tls": "enabled"})

    def _tls_relation_joined(self, _) -> None:
        """Handler for `certificates_relation_joined` event."""
        # generate unit private key if not already created by action
        truststore_password = (
            self.unit_tls_context.truststore_password or self.charm.workload.generate_password()
        )
        self.charm.workload.write(
            f"{ConnectLiterals.TRUSTSTORE_PASSWORD_KEY}={truststore_password}",
            self.charm.workload.connect_paths.truststore_password,
        )
        self.charm.context.worker_unit.update(
            {
                self.unit_tls_context.PRIVATE_KEY: self.unit_tls_context.private_key
                or generate_private_key().decode("utf-8"),
                self.unit_tls_context.KEYSTORE_PASSWORD: self.unit_tls_context.keystore_password
                or self.charm.workload.generate_password(),
                self.unit_tls_context.TRUSTSTORE_PASSWORD: truststore_password,
            }
        )

        self._request_certificate()

    def _tls_relation_broken(self, _) -> None:
        """Handler for `certificates_relation_broken` event."""
        self.charm.context.worker_unit.update(dict.fromkeys(self.unit_tls_context.KEYS, ""))

        # remove all existing keystores from the unit so we don't preserve certs
        self.charm.tls_manager.remove_stores(TLSScope.CONNECT)

        if not self.charm.unit.is_leader():
            return

        self.charm.context.peer_workers.update({"tls": ""})
        self.charm.on.config_changed.emit()

    def _on_certificate_available(self, event: CertificateAvailableEvent) -> None:
        """Handler for `certificates_available` event after provider updates signed certs."""
        if not self.charm.context.peer_workers:
            logger.warning("No peer relation on certificate available")
            event.defer()
            return

        # avoid setting tls files and restarting
        if event.certificate_signing_request != self.unit_tls_context.csr:
            logger.error("Can't use certificate, found unknown CSR")
            return

        self.charm.context.worker_unit.update(
            {
                self.unit_tls_context.CERT: event.certificate,
                self.unit_tls_context.CHAIN: json.dumps(event.chain),
                self.unit_tls_context.CA: event.ca,
            }
        )

        self.charm.tls_manager.configure()

        self.charm.on.config_changed.emit()

    def _on_certificate_expiring(self, _) -> None:
        """Handler for `certificate_expiring` event."""
        self._request_certificate_renewal()

    def _request_certificate(self):
        """Generates and submits CSR to provider."""
        if not self.unit_tls_context.private_key or not self.charm.context.peer_workers:
            logger.error("Can't request certificate, missing private key")
            return

        sans = self.charm.tls_manager.build_sans()

        csr = generate_csr(
            private_key=self.unit_tls_context.private_key.encode("utf-8"),
            subject=self.charm.context.worker_unit.internal_address,
            sans_ip=sans["sans_ip"],
            sans_dns=sans["sans_dns"],
        )
        self.charm.context.worker_unit.update(
            {self.unit_tls_context.CSR: csr.decode("utf-8").strip()}
        )

        self.certificates.request_certificate_creation(certificate_signing_request=csr)

    def _request_certificate_renewal(self):
        """Generates and submits new CSR to provider."""
        if (
            not self.unit_tls_context.private_key
            or not self.unit_tls_context.csr
            or not self.charm.context.peer_workers
        ):
            logger.error("Missing unit private key and/or old csr")
            return

        sans = self.charm.tls_manager.build_sans()
        new_csr = generate_csr(
            private_key=self.unit_tls_context.private_key.encode("utf-8"),
            subject=self.charm.context.worker_unit.internal_address,
            sans_ip=sans["sans_ip"],
            sans_dns=sans["sans_dns"],
        )

        self.certificates.request_certificate_renewal(
            old_certificate_signing_request=self.unit_tls_context.csr.encode("utf-8"),
            new_certificate_signing_request=new_csr,
        )

        self.charm.context.worker_unit.update(
            {self.unit_tls_context.CSR: new_csr.decode("utf-8").strip()}
        )
