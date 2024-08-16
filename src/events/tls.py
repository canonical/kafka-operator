#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka TLS configuration."""

import base64
import json
import logging
import os
import re
from typing import TYPE_CHECKING

from charms.tls_certificates_interface.v1.tls_certificates import (
    CertificateAvailableEvent,
    EventBase,
    TLSCertificatesRequiresV1,
    _load_relation_data,
    generate_csr,
    generate_private_key,
)
from ops.charm import (
    ActionEvent,
    RelationBrokenEvent,
    RelationChangedEvent,
    RelationJoinedEvent,
)
from ops.framework import Object
from ops.model import ActiveStatus

from literals import TLS_RELATION, TRUSTED_CA_RELATION, TRUSTED_CERTIFICATE_RELATION, Status

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)


class TLSHandler(Object):
    """Handler for managing the client and unit TLS keys/certs."""

    def __init__(self, charm: "KafkaCharm") -> None:
        super().__init__(charm, "tls")
        self.charm: "KafkaCharm" = charm

        self.certificates = TLSCertificatesRequiresV1(self.charm, TLS_RELATION)

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

        # External certificates handlers (for mTLS)
        for relation in [TRUSTED_CERTIFICATE_RELATION, TRUSTED_CA_RELATION]:
            self.framework.observe(
                self.charm.on[relation].relation_created,
                self._trusted_relation_created,
            )
            self.framework.observe(
                self.charm.on[relation].relation_joined,
                self._trusted_relation_joined,
            )
            self.framework.observe(
                self.charm.on[relation].relation_changed,
                self._trusted_relation_changed,
            )
            self.framework.observe(
                self.charm.on[relation].relation_broken,
                self._trusted_relation_broken,
            )

    def _tls_relation_created(self, _) -> None:
        """Handler for `certificates_relation_created` event."""
        if not self.charm.unit.is_leader() or not self.charm.state.peer_relation:
            return

        self.charm.state.cluster.update({"tls": "enabled"})

    def _tls_relation_joined(self, _) -> None:
        """Handler for `certificates_relation_joined` event."""
        # generate unit private key if not already created by action
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
            {"csr": "", "certificate": "", "ca": "", "ca-cert": ""}
        )

        # remove all existing keystores from the unit so we don't preserve certs
        self.charm.broker.tls_manager.remove_stores()
        self.charm.balancer.tls_manager.remove_stores()

        if not self.charm.unit.is_leader():
            return

        self.charm.state.cluster.update({"tls": ""})

    def _trusted_relation_created(self, event: EventBase) -> None:
        """Handle relation created event to trusted tls charm."""
        if not self.charm.unit.is_leader():
            return

        if not self.charm.state.cluster.tls_enabled:
            self.charm._set_status(Status.NO_CERT)
            event.defer()
            return

        # Create a "mtls" flag so a new listener (CLIENT_SSL) is created
        self.charm.state.cluster.update({"mtls": "enabled"})
        self.charm.app.status = ActiveStatus()

    def _trusted_relation_joined(self, event: RelationJoinedEvent) -> None:
        """Generate a CSR so the tls-certificates operator works as expected."""
        # Once the certificates have been added, TLS setup has finished
        if not self.charm.state.unit_broker.certificate:
            self.charm._set_status(Status.NO_CERT)
            event.defer()
            return

        alias = self.charm.broker.tls_manager.generate_alias(
            app_name=event.app.name,
            relation_id=event.relation.id,
        )
        subject = (
            os.uname()[1] if self.charm.substrate == "k8s" else self.charm.state.unit_broker.host
        )
        sans = self.charm.broker.tls_manager.build_sans()
        csr = (
            generate_csr(
                add_unique_id_to_subject_name=bool(alias),
                private_key=self.charm.state.unit_broker.private_key.encode("utf-8"),
                subject=subject,
                sans_ip=sans["sans_ip"],
                sans_dns=sans["sans_dns"],
            )
            .decode()
            .strip()
        )

        csr_dict = [{"certificate_signing_request": csr}]
        event.relation.data[self.model.unit]["certificate_signing_requests"] = json.dumps(csr_dict)

    def _trusted_relation_changed(self, event: RelationChangedEvent) -> None:
        """Overrides the requirer logic of TLSInterface."""
        if not event.relation or not event.relation.app:
            return

        # Once the certificates have been added, TLS setup has finished
        if not self.charm.state.unit_broker.certificate:
            logger.debug("Missing TLS relation, deferring")
            event.defer()
            return

        relation_data = _load_relation_data(dict(event.relation.data[event.relation.app]))
        provider_certificates = relation_data.get("certificates", [])

        if not provider_certificates:
            logger.warning("No certificates on provider side")
            event.defer()
            return

        alias = self.charm.broker.tls_manager.generate_alias(
            event.relation.app.name,
            event.relation.id,
        )
        # NOTE: Relation should only be used with one set of certificates,
        # hence using just the first item on the list.
        content = (
            provider_certificates[0]["certificate"]
            if event.relation.name == TRUSTED_CERTIFICATE_RELATION
            else provider_certificates[0]["ca"]
        )
        filename = f"{alias}.pem"
        self.charm.workload.write(
            content=content, path=f"{self.charm.workload.paths.conf_path}/{filename}"
        )
        self.charm.broker.tls_manager.import_cert(alias=f"{alias}", filename=filename)

        # ensuring new config gets applied
        self.charm.on[f"{self.charm.restart.name}"].acquire_lock.emit()

    def _trusted_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Handle relation broken for a trusted certificate/ca relation."""
        if not event.relation or not event.relation.app:
            return

        # Once the certificates have been added, TLS setup has finished
        if not self.charm.state.unit_broker.certificate:
            logger.debug("Missing TLS relation, deferring")
            event.defer()
            return

        # All units will need to remove the cert from their truststore
        alias = self.charm.broker.tls_manager.generate_alias(
            app_name=event.relation.app.name,
            relation_id=event.relation.id,
        )

        logger.info(f"Removing {alias=} from truststore...")
        self.charm.broker.tls_manager.remove_cert(alias=alias)

        # The leader will also handle removing the "mtls" flag if needed
        if not self.charm.unit.is_leader():
            return

        mtls_relations = set(
            self.model.relations[TRUSTED_CA_RELATION]
            + self.model.relations[TRUSTED_CERTIFICATE_RELATION]
        )
        for relation in mtls_relations:
            if relation == event.relation:
                mtls_relations.remove(event.relation)

        # No relations means that there are no certificates left in the truststore
        if not mtls_relations:
            self.charm.state.cluster.update({"mtls": ""})

    def _on_certificate_available(self, event: CertificateAvailableEvent) -> None:
        """Handler for `certificates_available` event after provider updates signed certs."""
        if not self.charm.state.peer_relation:
            logger.warning("No peer relation on certificate available")
            event.defer()
            return

        # avoid setting tls files and restarting
        if event.certificate_signing_request != self.charm.state.unit_broker.csr:
            logger.error("Can't use certificate, found unknown CSR")
            return

        self.charm.state.unit_broker.update(
            {"certificate": event.certificate, "ca-cert": event.ca, "ca": ""}
        )

        for dependent in ["broker", "balancer"]:
            getattr(self.charm, dependent).tls_manager.set_server_key()
            getattr(self.charm, dependent).tls_manager.set_ca()
            getattr(self.charm, dependent).tls_manager.set_certificate()
            getattr(self.charm, dependent).tls_manager.set_truststore()
            getattr(self.charm, dependent).tls_manager.set_keystore()

        # single-unit Kafka can lose restart events if it loses connection with TLS-enabled ZK
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
