#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka TLS configuration."""

import json
import logging
from typing import TYPE_CHECKING

from charms.tls_certificates_interface.v1.tls_certificates import (
    CertificateAvailableEvent,
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
from ops.model import ActiveStatus, BlockedStatus

from core.literals import TLS_RELATION, TRUSTED_CA_RELATION, TRUSTED_CERTIFICATE_RELATION
from managers.tls import TLSManager
from core.relation_interfaces import CertificatesRelation
from utils import generate_password, parse_tls_file

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)


class TLSHandler(Object):
    """Handler for managing the client and unit TLS keys/certs."""

    def __init__(self, charm):
        super().__init__(charm, "tls")
        self.charm: "KafkaCharm" = charm
        self.tls_manager = TLSManager(self.charm)
        self.certificates_relation = CertificatesRelation(self.charm)
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
        if not self.charm.unit.is_leader() or not self.charm.cluster.cluster_relation.peer_relation:
            return

        self.charm.cluster.cluster_relation.update(values={"tls": "enabled"})

    def _tls_relation_joined(self, _) -> None:
        """Handler for `certificates_relation_joined` event."""
        # generate unit private key if not already created by action
        if not self.charm.cluster.private_key:
            self.charm.cluster.cluster_relation.set_secret(
                scope="unit", key="private-key", value=generate_private_key().decode("utf-8")
            )

        # generate unit private key if not already created by action
        if not self.charm.cluster.keystore_password:
            self.charm.cluster.cluster_relation.set_secret(scope="unit", key="keystore-password", value=generate_password())
        if not self.charm.cluster.truststore_password:
            self.charm.cluster.cluster_relation.set_secret(
                scope="unit", key="truststore-password", value=generate_password()
            )

        self._request_certificate()

    def _tls_relation_broken(self, _) -> None:
        """Handler for `certificates_relation_broken` event."""
        self.charm.cluster.cluster_relation.set_secret(scope="unit", key="csr", value="")
        self.charm.cluster.cluster_relation.set_secret(scope="unit", key="certificate", value="")
        self.charm.cluster.cluster_relation.set_secret(scope="unit", key="ca", value="")

        # remove all existing keystores from the unit so we don't preserve certs
        self.tls_manager.remove_stores()

        if not self.charm.unit.is_leader():
            return

        self.charm.cluster.cluster_relation.update({"tls": ""})

    def _trusted_relation_created(self, _) -> None:
        """Handle relation created event to trusted tls charm."""
        if not self.charm.unit.is_leader():
            return

        if not self.charm.cluster.tls_enabled:
            msg = "Own certificates are not set. Please relate using 'certificates' relation first"
            logger.error(msg)
            self.charm.app.status = BlockedStatus(msg)
            return

        # Create a "mtls" flag so a new listener (CLIENT_SSL) is created
        self.charm.cluster.cluster_relation.update({"mtls": "enabled"})
        self.charm.app.status = ActiveStatus()

    def _trusted_relation_joined(self, event: RelationJoinedEvent) -> None:
        """Generate a CSR so the tls-certificates operator works as expected."""
        # Once the certificates have been added, TLS setup has finished
        if not self.charm.cluster.certificate:
            logger.debug("Missing TLS relation, deferring")
            event.defer()
            return

        alias = self.tls_manager.generate_alias(
            app_name=event.app.name,  # pyright: ignore[reportOptionalMemberAccess]
            relation_id=event.relation.id,
        )
        csr = (
            generate_csr(
                add_unique_id_to_subject_name=bool(alias),
                private_key=self.charm.cluster.private_key.encode(  # pyright: ignore[reportOptionalMemberAccess]
                    "utf-8"
                ),
                subject=self.charm.cluster.cluster_relation.unit_peer_data().get("private-address", ""),
                sans_ip=self.charm.cluster._sans["sans_ip"],
                sans_dns=self.charm.cluster._sans["sans_dns"],
            )
            .decode()
            .strip()
        )

        csr_dict = [{"certificate_signing_request": csr}]
        event.relation.data[self.model.unit]["certificate_signing_requests"] = json.dumps(csr_dict)

    def _trusted_relation_changed(self, event: RelationChangedEvent) -> None:
        """Overrides the requirer logic of TLSInterface."""
        # Once the certificates have been added, TLS setup has finished
        if not self.charm.cluster.certificate:
            logger.debug("Missing TLS relation, deferring")
            event.defer()
            return

        relation_data = _load_relation_data(dict(event.relation.data[event.relation.app]))  # type: ignore[reportOptionalMemberAccess]
        provider_certificates = relation_data.get("certificates", [])

        if not provider_certificates:
            logger.warning("No certificates on provider side")
            event.defer()
            return

        alias = self.tls_manager.generate_alias(
            event.relation.app.name,  # pyright: ignore[reportOptionalMemberAccess]
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
        self.charm.workload.write(content=content, path=f"{self.charm.workload.paths.conf_path}/{filename}")
        self.tls_manager.import_cert(alias=f"{alias}", filename=filename)

        # ensuring new config gets applied
        self.charm.on[f"{self.charm.restart.name}"].acquire_lock.emit()

    def _trusted_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Handle relation broken for a trusted certificate/ca relation."""
        # Once the certificates have been added, TLS setup has finished
        if not self.charm.cluster.certificate:
            logger.debug("Missing TLS relation, deferring")
            event.defer()
            return

        # All units will need to remove the cert from their truststore
        alias = self.tls_manager.generate_alias(
            app_name=event.relation.app.name,  # pyright: ignore[reportOptionalMemberAccess]
            relation_id=event.relation.id,
        )
        self.tls_manager.remove_cert(alias=alias)

        # The leader will also handle removing the "mtls" flag if needed
        if not self.charm.unit.is_leader():
            return

        # Get all relations, and remove the one being broken
        all_relations = (
            self.model.relations[TRUSTED_CA_RELATION]
            + self.model.relations[TRUSTED_CERTIFICATE_RELATION]
        )
        all_relations.remove(event.relation)
        logger.debug(f"Remaining relations: {all_relations}")

        # No relations means that there are no certificates left in the truststore
        if not all_relations:
            self.charm.cluster.cluster_relation.app_peer_data.update({"mtls": ""})

    def _on_certificate_available(self, event: CertificateAvailableEvent) -> None:
        """Handler for `certificates_available` event after provider updates signed certs."""
        if not self.charm.cluster.cluster_relation.peer_relation:
            logger.warning("No peer relation on certificate available")
            event.defer()
            return

        # avoid setting tls files and restarting
        if event.certificate_signing_request != self.charm.cluster.csr:
            logger.error("Can't use certificate, found unknown CSR")
            return

        self.charm.cluster.cluster_relation.set_secret(scope="unit", key="certificate", value=event.certificate)
        self.charm.cluster.cluster_relation.set_secret(scope="unit", key="ca", value=event.ca)

        self.tls_manager.set_server_key()
        self.tls_manager.set_ca()
        self.tls_manager.set_certificate()
        self.tls_manager.set_truststore()
        self.tls_manager.set_keystore()

    def _on_certificate_expiring(self, _) -> None:
        """Handler for `certificate_expiring` event."""
        if not self.charm.cluster.private_key or not self.charm.cluster.csr or not self.charm.cluster.cluster_relation.peer_relation:
            logger.error("Missing unit private key and/or old csr")
            return
        new_csr = generate_csr(
            private_key=self.charm.cluster.private_key.encode("utf-8"),
            subject=self.charm.cluster.cluster_relation.unit_peer_data().get("private-address", ""),
            sans_ip=self.charm.cluster._sans["sans_ip"],
            sans_dns=self.charm.cluster._sans["sans_dns"],
        )

        self.certificates.request_certificate_renewal(
            old_certificate_signing_request=self.charm.cluster.csr.encode("utf-8"),
            new_certificate_signing_request=new_csr,
        )

        self.charm.cluster.cluster_relation.set_secret(scope="unit", key="csr", value=new_csr.decode("utf-8").strip())

    def _set_tls_private_key(self, event: ActionEvent) -> None:
        """Handler for `set_tls_private_key` action."""
        private_key = (
            parse_tls_file(key)
            if (key := event.params.get("internal-key"))
            else generate_private_key().decode("utf-8")
        )

        self.charm.cluster.cluster_relation.set_secret(scope="unit", key="private-key", value=private_key)

        self._on_certificate_expiring(event)

    def _request_certificate(self):
        """Generates and submits CSR to provider."""
        if not self.charm.cluster.private_key or not self.charm.cluster.cluster_relation.peer_relation:
            logger.error("Can't request certificate, missing private key")
            return

        csr = generate_csr(
            private_key=self.charm.cluster.private_key.encode("utf-8"),
            subject=self.charm.cluster.cluster_relation.unit_peer_data().get("private-address", ""),
            sans_ip=self.charm.cluster._sans["sans_ip"],
            sans_dns=self.charm.cluster._sans["sans_dns"],
        )
        self.charm.cluster.cluster_relation.set_secret(scope="unit", key="csr", value=csr.decode("utf-8").strip())

        self.certificates.request_certificate_creation(certificate_signing_request=csr)
