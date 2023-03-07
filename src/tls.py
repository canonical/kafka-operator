#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka TLS configuration."""

import logging
import socket
import subprocess
from typing import Dict, List, Optional

from charms.tls_certificates_interface.v1.tls_certificates import (
    TLSCertificatesRequiresV1,
    generate_csr,
    generate_private_key,
)
from ops.charm import ActionEvent
from ops.framework import Object
from ops.model import Relation

from literals import TLS_RELATION
from snap import SNAP_CONFIG_PATH
from utils import generate_password, parse_tls_file, safe_write_to_file

logger = logging.getLogger(__name__)


class KafkaTLS(Object):
    """Handler for managing the client and unit TLS keys/certs."""

    def __init__(self, charm):
        super().__init__(charm, "tls")
        self.charm = charm
        self.certificates = TLSCertificatesRequiresV1(self.charm, TLS_RELATION)

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
        self.framework.observe(self.charm.on.set_tls_private_key_action, self._set_tls_private_key)

    def _tls_relation_created(self, _) -> None:
        """Handler for `certificates_relation_created` event."""
        if not self.charm.unit.is_leader():
            return

        self.peer_relation.data[self.charm.app].update({"tls": "enabled"})

    def _tls_relation_joined(self, _) -> None:
        """Handler for `certificates_relation_joined` event."""
        # generate unit private key if not already created by action
        if not self.private_key:
            self.charm.set_secret(
                scope="unit", key="private-key", value=generate_private_key().decode("utf-8")
            )

        # generate unit private key if not already created by action
        if not self.keystore_password:
            self.charm.set_secret(scope="unit", key="keystore-password", value=generate_password())
        if not self.truststore_password:
            self.charm.set_secret(
                scope="unit", key="truststore-password", value=generate_password()
            )

        self._request_certificate()

    def _tls_relation_broken(self, _) -> None:
        """Handler for `certificates_relation_broken` event."""
        self.charm.set_secret(scope="unit", key="csr", value="")
        self.charm.set_secret(scope="unit", key="certificate", value="")
        self.charm.set_secret(scope="unit", key="ca", value="")

        # remove all existing keystores from the unit so we don't preserve certs
        self.remove_stores()

        if not self.charm.unit.is_leader():
            return

        self.peer_relation.data[self.charm.app].update({"tls": ""})

    def _on_certificate_available(self, event) -> None:
        """Handler for `certificates_available` event after provider updates signed certs."""
        if not self.peer_relation:
            logger.warning("No peer relation on certificate available")
            event.defer()
            return

        # avoid setting tls files and restarting
        if event.certificate_signing_request != self.csr:
            logger.error("Can't use certificate, found unknown CSR")
            return

        self.charm.set_secret(scope="unit", key="certificate", value=event.certificate)
        self.charm.set_secret(scope="unit", key="ca", value=event.ca)

        self.set_server_key()
        self.set_ca()
        self.set_certificate()
        self.set_truststore()
        self.set_keystore()

    def _on_certificate_expiring(self, _) -> None:
        """Handler for `certificate_expiring` event."""
        if not self.private_key or not self.csr:
            logger.error("Missing unit private key and/or old csr")
            return
        new_csr = generate_csr(
            private_key=self.private_key.encode("utf-8"),
            subject=self.peer_relation.data[self.charm.unit].get("private-address", ""),
            **self._sans,
        )

        self.certificates.request_certificate_renewal(
            old_certificate_signing_request=self.csr.encode("utf-8"),
            new_certificate_signing_request=new_csr,
        )

        self.charm.set_secret(scope="unit", key="csr", value=new_csr.decode("utf-8").strip())

    def _set_tls_private_key(self, event: ActionEvent) -> None:
        """Handler for `set_tls_private_key` action."""
        private_key = (
            parse_tls_file(key)
            if (key := event.params.get("internal-key"))
            else generate_private_key().decode("utf-8")
        )

        self.charm.set_secret(scope="unit", key="private-key", value=private_key)

        self._on_certificate_expiring(event)

    @property
    def peer_relation(self) -> Relation:
        """Get the peer relation of the charm."""
        return self.charm.peer_relation

    @property
    def enabled(self) -> bool:
        """Flag to check if the cluster should run with TLS.

        Returns:
            True if TLS encryption should be active. Otherwise False
        """
        return self.peer_relation.data[self.charm.app].get("tls", "disabled") == "enabled"

    @property
    def private_key(self) -> Optional[str]:
        """The unit private-key set during `certificates_joined`.

        Returns:
            String of key contents
            None if key not yet generated
        """
        return self.charm.get_secret(scope="unit", key="private-key")

    @property
    def csr(self) -> Optional[str]:
        """The unit cert signing request.

        Returns:
            String of csr contents
            None if csr not yet generated
        """
        return self.charm.get_secret(scope="unit", key="csr")

    @property
    def certificate(self) -> Optional[str]:
        """The signed unit certificate from the provider relation.

        Returns:
            String of cert contents in PEM format
            None if cert not yet generated/signed
        """
        return self.charm.get_secret(scope="unit", key="certificate")

    @property
    def ca(self) -> Optional[str]:
        """The ca used to sign unit cert.

        Returns:
            String of ca contents in PEM format
            None if cert not yet generated/signed
        """
        return self.charm.get_secret(scope="unit", key="ca")

    @property
    def keystore_password(self) -> Optional[str]:
        """The unit keystore password set during `certificates_joined`.

        Returns:
            String of password
            None if password not yet generated
        """
        return self.charm.get_secret(scope="unit", key="keystore-password")

    @property
    def truststore_password(self) -> Optional[str]:
        """The unit truststore password set during `certificates_joined`.

        Returns:
            String of password
            None if password not yet generated
        """
        return self.charm.get_secret(scope="unit", key="truststore-password")

    def _request_certificate(self):
        """Generates and submits CSR to provider."""
        if not self.private_key:
            logger.error("Can't request certificate, missing private key")
            return

        csr = generate_csr(
            private_key=self.private_key.encode("utf-8"),
            subject=self.peer_relation.data[self.charm.unit].get("private-address", ""),
            **self._sans,
        )
        self.charm.set_secret(scope="unit", key="csr", value=csr.decode("utf-8").strip())

        self.certificates.request_certificate_creation(certificate_signing_request=csr)

    @property
    def _sans(self) -> Dict[str, List[str]]:
        """Builds a SAN dict of DNS names and IPs for the unit."""
        unit_host = self.peer_relation.data[self.charm.unit].get("private-address", "")
        unit_name = self.charm.unit.name

        return {
            "sans_ip": [unit_host],
            "sans_dns": [unit_name, socket.getfqdn()],
        }

    def set_server_key(self) -> None:
        """Sets the unit private-key."""
        if not self.private_key:
            logger.error("Can't set private-key to unit, missing private-key in relation data")
            return

        safe_write_to_file(content=self.private_key, path=f"{SNAP_CONFIG_PATH}/server.key")

    def set_ca(self) -> None:
        """Sets the unit ca."""
        if not self.ca:
            logger.error("Can't set CA to unit, missing CA in relation data")
            return

        safe_write_to_file(content=self.ca, path=f"{SNAP_CONFIG_PATH}/ca.pem")

    def set_certificate(self) -> None:
        """Sets the unit certificate."""
        if not self.certificate:
            logger.error("Can't set certificate to unit, missing certificate in relation data")
            return

        safe_write_to_file(content=self.certificate, path=f"{SNAP_CONFIG_PATH}/server.pem")

    def set_truststore(self) -> None:
        """Adds CA to JKS truststore."""
        try:
            subprocess.check_output(
                f"keytool -import -v -alias ca -file ca.pem -keystore truststore.jks -storepass {self.truststore_password} -noprompt",
                stderr=subprocess.PIPE,
                shell=True,
                universal_newlines=True,
                cwd=SNAP_CONFIG_PATH,
            )
        except subprocess.CalledProcessError as e:
            # in case this reruns and fails
            if "already exists" in e.output:
                return
            logger.error(e.output)
            raise e

    def set_keystore(self) -> None:
        """Creates and adds unit cert and private-key to the keystore."""
        try:
            subprocess.check_output(
                f"openssl pkcs12 -export -in server.pem -inkey server.key -passin pass:{self.keystore_password} -certfile server.pem -out keystore.p12 -password pass:{self.keystore_password}",
                stderr=subprocess.PIPE,
                shell=True,
                universal_newlines=True,
                cwd=SNAP_CONFIG_PATH,
            )
        except subprocess.CalledProcessError as e:
            logger.error(e.output)
            raise e

    def remove_stores(self) -> None:
        """Cleans up all keys/certs/stores on a unit."""
        try:
            subprocess.check_output(
                "rm -rf *.pem *.key *.p12 *.jks",
                stderr=subprocess.PIPE,
                shell=True,
                universal_newlines=True,
                cwd=SNAP_CONFIG_PATH,
            )
        except subprocess.CalledProcessError as e:
            logger.error(e.output)
            raise e
