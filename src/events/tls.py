#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka TLS configuration."""

import base64
import json
import logging
import os
import re
import socket
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

from literals import TLS_RELATION, TRUSTED_CA_RELATION, TRUSTED_CERTIFICATE_RELATION

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)


class TLSHandler(Object):
    """Handler for managing the client and unit TLS keys/certs."""

    def __init__(self, charm):
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
        if not self.charm.state.broker.private_key:
            self.charm.state.broker.update({"private-key": generate_private_key().decode("utf-8")})

        # generate unit private key if not already created by action
        if not self.charm.state.broker.keystore_password:
            self.charm.state.broker.update(
                {"keystore-password": self.charm.workload.generate_password()}
            )
        if not self.charm.state.broker.truststore_password:
            self.charm.state.broker.update(
                {"truststore-password": self.charm.workload.generate_password()}
            )

        self._request_certificate()

    def _tls_relation_broken(self, _) -> None:
        """Handler for `certificates_relation_broken` event."""
        self.charm.state.broker.update({"csr": ""})
        self.charm.state.broker.update({"certificate": ""})
        self.charm.state.broker.update({"ca": ""})

        # remove all existing keystores from the unit so we don't preserve certs
        self.charm.tls_manager.remove_stores()

        if not self.charm.unit.is_leader():
            return

        self.charm.state.cluster.update({"tls": ""})

    def _trusted_relation_created(self, _) -> None:
        """Handle relation created event to trusted tls charm."""
        if not self.charm.unit.is_leader():
            return

        if not self.charm.state.cluster.tls_enabled:
            msg = "Own certificates are not set. Please relate using 'certificates' relation first"
            logger.error(msg)
            self.charm.app.status = BlockedStatus(msg)
            return

        # Create a "mtls" flag so a new listener (CLIENT_SSL) is created
        self.charm.state.cluster.update({"mtls": "enabled"})
        self.charm.app.status = ActiveStatus()

    def _trusted_relation_joined(self, event: RelationJoinedEvent) -> None:
        """Generate a CSR so the tls-certificates operator works as expected."""
        # Once the certificates have been added, TLS setup has finished
        if not self.charm.state.broker.certificate:
            logger.debug("Missing TLS relation, deferring")
            event.defer()
            return

        alias = self.charm.tls_manager.generate_alias(
            app_name=event.app.name,  # pyright: ignore[reportOptionalMemberAccess]
            relation_id=event.relation.id,
        )
        subject = os.uname()[1] if self.charm.substrate == "k8s" else self.charm.state.broker.host
        csr = (
            generate_csr(
                add_unique_id_to_subject_name=bool(alias),
                private_key=self.charm.state.broker.private_key.encode(  # pyright: ignore[reportOptionalMemberAccess]
                    "utf-8"
                ),
                subject=subject,
                sans_ip=self._sans["sans_ip"],
                sans_dns=self._sans["sans_dns"],
            )
            .decode()
            .strip()
        )

        csr_dict = [{"certificate_signing_request": csr}]
        event.relation.data[self.model.unit]["certificate_signing_requests"] = json.dumps(csr_dict)

    def _trusted_relation_changed(self, event: RelationChangedEvent) -> None:
        """Overrides the requirer logic of TLSInterface."""
        # Once the certificates have been added, TLS setup has finished
        if not self.charm.state.broker.certificate:
            logger.debug("Missing TLS relation, deferring")
            event.defer()
            return

        relation_data = _load_relation_data(dict(event.relation.data[event.relation.app]))  # type: ignore[reportOptionalMemberAccess]
        provider_certificates = relation_data.get("certificates", [])

        if not provider_certificates:
            logger.warning("No certificates on provider side")
            event.defer()
            return

        alias = self.charm.tls_manager.generate_alias(
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
        self.charm.workload.write(
            content=content, path=f"{self.charm.workload.paths.conf_path}/{filename}"
        )
        self.charm.tls_manager.import_cert(alias=f"{alias}", filename=filename)

        # ensuring new config gets applied
        self.charm.on[f"{self.charm.restart.name}"].acquire_lock.emit()

    def _trusted_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Handle relation broken for a trusted certificate/ca relation."""
        # Once the certificates have been added, TLS setup has finished
        if not self.charm.state.broker.certificate:
            logger.debug("Missing TLS relation, deferring")
            event.defer()
            return

        # All units will need to remove the cert from their truststore
        alias = self.charm.tls_manager.generate_alias(
            app_name=event.relation.app.name,  # pyright: ignore[reportOptionalMemberAccess]
            relation_id=event.relation.id,
        )

        logger.info(f"Removing {alias=} from truststore...")
        self.charm.tls_manager.remove_cert(alias=alias)

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
        if event.certificate_signing_request != self.charm.state.broker.csr:
            logger.error("Can't use certificate, found unknown CSR")
            return

        self.charm.state.broker.update({"certificate": event.certificate})
        self.charm.state.broker.update({"ca": event.ca})

        self.charm.tls_manager.set_server_key()
        self.charm.tls_manager.set_ca()
        self.charm.tls_manager.set_certificate()
        self.charm.tls_manager.set_truststore()
        self.charm.tls_manager.set_keystore()

    def _on_certificate_expiring(self, _) -> None:
        """Handler for `certificate_expiring` event."""
        if (
            not self.charm.state.broker.private_key
            or not self.charm.state.broker.csr
            or not self.charm.state.peer_relation
        ):
            logger.error("Missing unit private key and/or old csr")
            return
        new_csr = generate_csr(
            private_key=self.charm.state.broker.private_key.encode("utf-8"),
            subject=self.charm.state.broker.relation_data.get("private-address", ""),
            sans_ip=self._sans["sans_ip"],
            sans_dns=self._sans["sans_dns"],
        )

        self.certificates.request_certificate_renewal(
            old_certificate_signing_request=self.charm.state.broker.csr.encode("utf-8"),
            new_certificate_signing_request=new_csr,
        )

        self.charm.state.broker.update({"csr": new_csr.decode("utf-8").strip()})

    def _set_tls_private_key(self, event: ActionEvent) -> None:
        """Handler for `set_tls_private_key` action."""
        key = event.params.get("internal-key") or generate_private_key().decode("utf-8")
        private_key = (
            key
            if re.match(r"(-+(BEGIN|END) [A-Z ]+-+)", key)
            else base64.b64decode(key).decode("utf-8")
        )

        self.charm.state.broker.update({"private-key": private_key})
        self._on_certificate_expiring(event)

    def _request_certificate(self):
        """Generates and submits CSR to provider."""
        if not self.charm.state.broker.private_key or not self.charm.state.peer_relation:
            logger.error("Can't request certificate, missing private key")
            return

        csr = generate_csr(
            private_key=self.charm.state.broker.private_key.encode("utf-8"),
            subject=self.charm.state.broker.relation_data.get("private-address", ""),
            sans_ip=self._sans["sans_ip"],
            sans_dns=self._sans["sans_dns"],
        )
        self.charm.state.broker.update({"csr": csr.decode("utf-8").strip()})

        self.certificates.request_certificate_creation(certificate_signing_request=csr)

    @property
    def _sans(self) -> dict[str, list[str] | None]:
        """Builds a SAN dict of DNS names and IPs for the unit."""
        if self.charm.substrate == "vm":
            return {
                "sans_ip": [self.charm.state.broker.host],
                "sans_dns": [self.model.unit.name, socket.getfqdn()] + self._extra_sans,
            }
        else:
            bind_address = ""
            if self.charm.state.peer_relation:
                if binding := self.charm.model.get_binding(self.charm.state.peer_relation):
                    bind_address = binding.network.bind_address
            return {
                "sans_ip": [str(bind_address)],
                "sans_dns": [
                    self.charm.state.broker.host.split(".")[0],
                    self.charm.state.broker.host,
                    socket.getfqdn(),
                ]
                + self._extra_sans,
            }

    @property
    def _extra_sans(self) -> list[str]:
        """Parse the certificate_extra_sans config option."""
        extra_sans = self.charm.config.certificate_extra_sans or ""
        parsed_sans = []

        if extra_sans == "":
            return parsed_sans

        for sans in extra_sans.split(","):
            parsed_sans.append(sans.replace("{unit}", self.charm.unit.name.split("/")[1]))

        return parsed_sans
