#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Collection of globals common to the KafkaCharm."""

import socket
from typing import TYPE_CHECKING, Dict, List, Optional
from ops import Object, Unit

from core.relation_interfaces import ClusterRelation, ZooKeeperRelation
from core.literals import INTERNAL_USERS, SECURITY_PROTOCOL_PORTS, Status

if TYPE_CHECKING:
    from charm import KafkaCharm


class ClusterState(Object):
    """Properties and relations of the charm."""

    def __init__(self, charm):
        super().__init__(charm, "cluster_state")
        self.charm: "KafkaCharm" = charm
        self.cluster_relation = ClusterRelation(charm)

    def unit_host(self, unit: Unit | None = None) -> str:
        """Return the hostname of a unit."""
        host = ""
        unit = unit or self.model.unit

        if self.charm.substrate == "vm":
            host = self.cluster_relation.unit_peer_data(unit).get("private-address", "")
        if self.charm.substrate == "k8s":
            broker_id = unit.name.split("/")[1]
            host = f"{self.charm.app.name}-{broker_id}.{self.charm.app.name}-endpoints"

        return host

    @property
    def unit_hosts(self) -> List[str]:
        """Return list of application unit hosts."""
        hosts = [self.unit_host(unit) for unit in self.cluster_relation.units] + [self.unit_host()]
        return hosts

    @property
    def internal_user_credentials(self) -> Dict[str, str]:
        """The charm internal usernames and passwords, e.g `sync` and `admin`.

        Returns:
            Dict of usernames and passwords
        """
        credentials = {
            user: password
            for user in INTERNAL_USERS
            if (password := self.cluster_relation.get_secret(scope="app", key=f"{user}-password"))
        }

        if not len(credentials) == len(INTERNAL_USERS):
            return {}

        return credentials

    @property
    def bootstrap_server(self) -> List[str]:
        """The current Kafka uris formatted for the `bootstrap-server` command flag.

        Returns:
            List of `bootstrap-server` servers
        """
        if not self.cluster_relation.peer_relation:
            return []

        port = (
            SECURITY_PROTOCOL_PORTS["SASL_SSL"].client
            if (self.tls_enabled and self.certificate)
            else SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT"].client
        )
        return [f"{host}:{port}" for host in self.unit_hosts]

    ##### TLS #####

    @property
    def tls_enabled(self) -> bool:
        """Flag to check if the cluster should run with TLS.

        Returns:
            True if TLS encryption should be active. Otherwise False
        """
        return self.cluster_relation.app_peer_data.get("tls", "disabled") == "enabled"

    @property
    def mtls_enabled(self) -> bool:
        """Flag to check if the cluster should run with mTLS.

        Returns:
            True if TLS encryption should be active. Otherwise False
        """
        return self.cluster_relation.app_peer_data.get("mtls", "disabled") == "enabled"

    @property
    def private_key(self) -> Optional[str]:
        """The unit private-key set during `certificates_joined`.

        Returns:
            String of key contents
            None if key not yet generated
        """
        return self.cluster_relation.get_secret(scope="unit", key="private-key")

    @property
    def csr(self) -> Optional[str]:
        """The unit cert signing request.

        Returns:
            String of csr contents
            None if csr not yet generated
        """
        return self.cluster_relation.get_secret(scope="unit", key="csr")

    @property
    def certificate(self) -> Optional[str]:
        """The signed unit certificate from the provider relation.

        Returns:
            String of cert contents in PEM format
            None if cert not yet generated/signed
        """
        return self.cluster_relation.get_secret(scope="unit", key="certificate")

    @property
    def ca(self) -> Optional[str]:
        """The ca used to sign unit cert.

        Returns:
            String of ca contents in PEM format
            None if cert not yet generated/signed
        """
        return self.cluster_relation.get_secret(scope="unit", key="ca")

    @property
    def keystore_password(self) -> Optional[str]:
        """The unit keystore password set during `certificates_joined`.

        Returns:
            String of password
            None if password not yet generated
        """
        return self.cluster_relation.get_secret(scope="unit", key="keystore-password")

    @property
    def truststore_password(self) -> Optional[str]:
        """The unit truststore password set during `certificates_joined`.

        Returns:
            String of password
            None if password not yet generated
        """
        return self.cluster_relation.get_secret(scope="unit", key="truststore-password")

    @property
    def _extra_sans(self) -> List[str]:
        """Parse the certificate_extra_sans config option."""
        extra_sans = self.charm.config.certificate_extra_sans or ""
        parsed_sans = []

        if extra_sans == "":
            return parsed_sans

        for sans in extra_sans.split(","):
            parsed_sans.append(sans.replace("{unit}", self.charm.unit.name.split("/")[1]))

        return parsed_sans

    @property
    def _sans(self) -> Dict[str, List[str]]:
        """Builds a SAN dict of DNS names and IPs for the unit."""
        return {
            "sans_ip": [self.unit_host()],
            "sans_dns": [self.model.unit.name, socket.getfqdn()] + self._extra_sans,
        }

    ##### HEALTH #####

    @property
    def ready_to_start(self) -> bool:
        """Check for active ZooKeeper relation and adding of inter-broker auth username.

        Returns:
            True if ZK is related and `sync` user has been added. False otherwise.
        """
        if not self.cluster_relation.peer_relation:
            self.charm._set_status(Status.NO_PEER_RELATION)
            return False

        if not self.charm.zookeeper.zookeeper_related:
            self.charm._set_status(Status.ZK_NOT_RELATED)
            return False

        if not self.charm.zookeeper.zookeeper_connected:
            self.charm._set_status(Status.ZK_NO_DATA)
            return False

        # TLS must be enabled for Kafka and ZK or disabled for both
        if self.tls_enabled ^ (
            self.charm.zookeeper.zookeeper_config.get("tls", "disabled") == "enabled"
        ):
            self.charm._set_status(Status.ZK_TLS_MISMATCH)
            return False

        if not self.internal_user_credentials:
            self.charm._set_status(Status.NO_BROKER_CREDS)
            return False

        return True

    @property
    def healthy(self) -> bool:
        """Checks and updates various charm lifecycle states.

        Is slow to fail due to retries, to be used sparingly.

        Returns:
            True if service is alive and active. Otherwise False
        """
        if not self.ready_to_start:
            return False

        if not self.charm.workload.active():
            self.charm._set_status(Status.SNAP_NOT_RUNNING)
            return False

        return True
