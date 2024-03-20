#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Collection of state objects for the Kafka relations, apps and units."""

import json
import logging
from typing import MutableMapping, TypeAlias

from charms.zookeeper.v0.client import QuorumLeaderNotFoundError, ZooKeeperManager
from kazoo.exceptions import AuthFailedError, NoNodeError
from ops.model import Application, Relation, Unit
from tenacity import retry, retry_if_not_result, stop_after_attempt, wait_fixed

from literals import INTERNAL_USERS, Substrate

logger = logging.getLogger(__name__)

JSON: TypeAlias = dict[str, "JSON"] | list["JSON"] | str | int | float | bool | None


class StateBase:
    """Base state object."""

    def __init__(
        self, relation: Relation | None, component: Unit | Application, substrate: Substrate
    ):
        self.relation = relation
        self.component = component
        self.substrate = substrate

    @property
    def relation_data(self) -> MutableMapping[str, str]:
        """The raw relation data."""
        if not self.relation:
            return {}

        return self.relation.data[self.component]

    def update(self, items: dict[str, str]) -> None:
        """Writes to relation_data."""
        if not self.relation:
            return

        self.relation_data.update(items)


class KafkaCluster(StateBase):
    """State collection metadata for the peer relation."""

    def __init__(self, relation: Relation | None, component: Application, substrate: Substrate):
        super().__init__(relation, component, substrate)
        self.app = component

    @property
    def internal_user_credentials(self) -> dict[str, str]:
        """The charm internal usernames and passwords, e.g `sync` and `admin`.

        Returns:
            Dict of usernames and passwords
        """
        credentials = {
            user: password
            for user in INTERNAL_USERS
            if (password := self.relation_data.get(f"{user}-password"))
        }

        if not len(credentials) == len(INTERNAL_USERS):
            return {}

        return credentials

    @property
    def client_passwords(self) -> dict[str, str]:
        """Usernames and passwords of related client applications."""
        return {key: value for key, value in self.relation_data.items() if "relation-" in key}

    # --- TLS ---

    @property
    def tls_enabled(self) -> bool:
        """Flag to check if the cluster should run with TLS.

        Returns:
            True if TLS encryption should be active. Otherwise False
        """
        return self.relation_data.get("tls", "disabled") == "enabled"

    @property
    def mtls_enabled(self) -> bool:
        """Flag to check if the cluster should run with mTLS.

        Returns:
            True if TLS encryption should be active. Otherwise False
        """
        return self.relation_data.get("mtls", "disabled") == "enabled"


class KafkaBroker(StateBase):
    """State collection metadata for a charm unit."""

    def __init__(self, relation: Relation | None, component: Unit, substrate: Substrate):
        super().__init__(relation, component, substrate)
        self.unit = component

    @property
    def unit_id(self) -> int:
        """The id of the unit from the unit name.

        e.g kafka/2 --> 2
        """
        return int(self.component.name.split("/")[1])

    @property
    def host(self) -> str:
        """Return the hostname of a unit."""
        host = ""
        if self.substrate == "vm":
            for key in ["hostname", "ip", "private-address"]:
                if host := self.relation_data.get(key, ""):
                    break
        if self.substrate == "k8s":
            host = f"{self.component.name.split('/')[0]}-{self.unit_id}.{self.component.name.split('/')[0]}-endpoints"

        return host

    # --- CRUISE CONTROL ---

    @property
    def storages(self) -> JSON:
        """The current Juju storages for the unit."""
        return json.loads(self.relation_data.get("storages", ""))

    @property
    def cores(self) -> int:
        """The number of CPU cores for the unit machine."""
        return int(self.relation_data.get("cores", ""))

    # --- TLS ---

    @property
    def private_key(self) -> str | None:
        """The unit private-key set during `certificates_joined`.

        Returns:
            String of key contents
            None if key not yet generated
        """
        return self.relation_data.get("private-key")

    @property
    def csr(self) -> str | None:
        """The unit cert signing request.

        Returns:
            String of csr contents
            None if csr not yet generated
        """
        return self.relation_data.get("csr")

    @property
    def certificate(self) -> str | None:
        """The signed unit certificate from the provider relation.

        Returns:
            String of cert contents in PEM format
            None if cert not yet generated/signed
        """
        return self.relation_data.get("certificate")

    @property
    def ca(self) -> str | None:
        """The ca used to sign unit cert.

        Returns:
            String of ca contents in PEM format
            None if cert not yet generated/signed
        """
        return self.relation_data.get("ca")

    @property
    def keystore_password(self) -> str | None:
        """The unit keystore password set during `certificates_joined`.

        Returns:
            String of password
            None if password not yet generated
        """
        return self.relation_data.get("keystore-password")

    @property
    def truststore_password(self) -> str | None:
        """The unit truststore password set during `certificates_joined`.

        Returns:
            String of password
            None if password not yet generated
        """
        return self.relation_data.get("truststore-password")


class ZooKeeper(StateBase):
    """State collection metadata for a the Zookeeper relation."""

    def __init__(
        self,
        relation: Relation | None,
        component: Application,
        substrate: Substrate,
        local_unit: Unit,
        local_app: Application | None = None,
    ):
        super().__init__(relation, component, substrate)
        self._local_app = local_app
        self._local_unit = local_unit

    # APPLICATION DATA

    @property
    def remote_app_data(self) -> MutableMapping[str, str]:
        """Zookeeper relation data object."""
        if not self.relation or not self.relation.app:
            return {}

        return self.relation.data[self.relation.app]

    @property
    def app_data(self) -> MutableMapping[str, str]:
        """Zookeeper relation data object."""
        if not self.relation or not self._local_app:
            return {}

        return self.relation.data[self._local_app]

    # --- RELATION PROPERTIES ---

    @property
    def zookeeper_related(self) -> bool:
        """Checks if there is a relation with ZooKeeper.

        Returns:
            True if there is a ZooKeeper relation. Otherwise False
        """
        return bool(self.relation)

    @property
    def username(self) -> str:
        """Username to connect to ZooKeeper."""
        return self.remote_app_data.get("username", "")

    @property
    def password(self) -> str:
        """Password of the ZooKeeper user."""
        return self.remote_app_data.get("password", "")

    @property
    def endpoints(self) -> str:
        """IP/host where ZooKeeper is located."""
        return self.remote_app_data.get("endpoints", "")

    @property
    def chroot(self) -> str:
        """Path allocated for Kafka on ZooKeeper."""
        return self.remote_app_data.get("chroot", "")

    @property
    def uris(self) -> str:
        """Comma separated connection string, containing endpoints + chroot."""
        return self.remote_app_data.get("uris", "")

    @property
    def tls(self) -> bool:
        """Check if TLS is enabled on ZooKeeper."""
        return bool(self.remote_app_data.get("tls", "disabled") == "enabled")

    @property
    def connect(self) -> str:
        """Full connection string of sorted uris."""
        sorted_uris = sorted(self.uris.replace(self.chroot, "").split(","))
        sorted_uris[-1] = sorted_uris[-1] + self.chroot
        return ",".join(sorted_uris)

    @property
    def zookeeper_connected(self) -> bool:
        """Checks if there is an active ZooKeeper relation with all necessary data.

        Returns:
            True if ZooKeeper is currently related with sufficient relation data
                for a broker to connect with. Otherwise False
        """
        if not all([self.username, self.password, self.endpoints, self.chroot, self.uris]):
            return False

        return True

    @property
    def zookeeper_version(self) -> str:
        """Get running zookeeper version."""
        hosts = self.endpoints.split(",")
        zk = ZooKeeperManager(hosts=hosts, username=self.username, password=self.password)

        return zk.get_version()

    @retry(
        # retry to give ZK time to update its broker zNodes before failing
        wait=wait_fixed(6),
        stop=stop_after_attempt(10),
        retry_error_callback=(lambda state: state.outcome.result()),  # type: ignore
        retry=retry_if_not_result(lambda result: True if result else False),
    )
    def broker_active(self) -> bool:
        """Checks if broker id is recognised as active by ZooKeeper."""
        broker_id = self._local_unit.name.split("/")[1]
        brokers = self.get_active_brokers()
        return f"{self.chroot}/brokers/ids/{broker_id}" in brokers

    def get_active_brokers(self) -> set[str]:
        """Gets all brokers currently connected to ZooKeeper."""
        hosts = self.endpoints.split(",")
        zk = ZooKeeperManager(hosts=hosts, username=self.username, password=self.password)
        path = f"{self.chroot}/brokers/ids/"

        try:
            brokers = zk.leader_znodes(path=path)
        # auth might not be ready with ZK after relation yet
        except (NoNodeError, AuthFailedError, QuorumLeaderNotFoundError) as e:
            logger.debug(str(e))
            return set()

        return brokers
