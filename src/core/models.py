#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Collection of state objects for the Kafka relations, apps and units."""

import logging
from typing import Dict, MutableMapping, Optional, Set

from charms.zookeeper.v0.client import QuorumLeaderNotFoundError, ZooKeeperManager
from kazoo.exceptions import AuthFailedError, NoNodeError
from ops.model import Application, Relation, Unit
from tenacity import retry, retry_if_not_result, stop_after_attempt, wait_fixed

from core.literals import INTERNAL_USERS, Substrate

logger = logging.getLogger(__name__)


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
    def internal_user_credentials(self) -> Dict[str, str]:
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

    # --- TLS ---

    @property
    def private_key(self) -> Optional[str]:
        """The unit private-key set during `certificates_joined`.

        Returns:
            String of key contents
            None if key not yet generated
        """
        return self.relation_data.get("private-key")

    @property
    def csr(self) -> Optional[str]:
        """The unit cert signing request.

        Returns:
            String of csr contents
            None if csr not yet generated
        """
        return self.relation_data.get("csr")

    @property
    def certificate(self) -> Optional[str]:
        """The signed unit certificate from the provider relation.

        Returns:
            String of cert contents in PEM format
            None if cert not yet generated/signed
        """
        return self.relation_data.get("certificate")

    @property
    def ca(self) -> Optional[str]:
        """The ca used to sign unit cert.

        Returns:
            String of ca contents in PEM format
            None if cert not yet generated/signed
        """
        return self.relation_data.get("ca")

    @property
    def keystore_password(self) -> Optional[str]:
        """The unit keystore password set during `certificates_joined`.

        Returns:
            String of password
            None if password not yet generated
        """
        return self.relation_data.get("keystore-password")

    @property
    def truststore_password(self) -> Optional[str]:
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
    def zookeeper_config(self) -> dict[str, str]:
        """The config from current ZooKeeper relations for data necessary for broker connection.

        Returns:
            Dict of ZooKeeeper:
            `username`, `password`, `endpoints`, `chroot`, `connect`, `uris` and `tls`
        """
        zookeeper_config = {}

        if not self.relation:
            return zookeeper_config

        zk_keys = ["username", "password", "endpoints", "chroot", "uris", "tls"]
        missing_config = any(self.remote_app_data.get(key, None) is None for key in zk_keys)

        # skip if config is missing
        if missing_config:
            return zookeeper_config

        # set if exists
        zookeeper_config.update(self.remote_app_data)

        if zookeeper_config:
            sorted_uris = sorted(
                zookeeper_config["uris"].replace(zookeeper_config["chroot"], "").split(",")
            )
            sorted_uris[-1] = sorted_uris[-1] + zookeeper_config["chroot"]
            zookeeper_config["connect"] = ",".join(sorted_uris)

        return zookeeper_config

    @property
    def zookeeper_connected(self) -> bool:
        """Checks if there is an active ZooKeeper relation with all necessary data.

        Returns:
            True if ZooKeeper is currently related with sufficient relation data
                for a broker to connect with. Otherwise False
        """
        if self.zookeeper_config.get("connect", None):
            return True

        return False

    @property
    def tls(self) -> bool:
        """Check if TLS is enabled on ZooKeeper."""
        return bool(self.zookeeper_config.get("tls", "disabled") == "enabled")

    def get_zookeeper_version(self) -> str:
        """Get running zookeeper version.

        Args:
            zookeeper_config: the relation provided by ZooKeeper

        Returns:
            zookeeper version
        """
        config = self.zookeeper_config
        hosts = config.get("endpoints", "").split(",")
        username = config.get("username", "")
        password = config.get("password", "")

        zk = ZooKeeperManager(hosts=hosts, username=username, password=password)

        return zk.get_version()

    def get_active_brokers(self) -> Set[str]:
        """Gets all brokers currently connected to ZooKeeper.

        Args:
            zookeeper_config: the relation data provided by ZooKeeper

        Returns:
            Set of active broker ids
        """
        config = self.zookeeper_config
        chroot = config.get("chroot", "")
        hosts = config.get("endpoints", "").split(",")
        username = config.get("username", "")
        password = config.get("password", "")

        zk = ZooKeeperManager(hosts=hosts, username=username, password=password)
        path = f"{chroot}/brokers/ids/"

        try:
            brokers = zk.leader_znodes(path=path)
        # auth might not be ready with ZK after relation yet
        except (NoNodeError, AuthFailedError, QuorumLeaderNotFoundError) as e:
            logger.debug(str(e))
            return set()

        return brokers

    @retry(
        # retry to give ZK time to update its broker zNodes before failing
        wait=wait_fixed(6),
        stop=stop_after_attempt(10),
        retry_error_callback=(lambda state: state.outcome.result()),  # type: ignore
        retry=retry_if_not_result(lambda result: True if result else False),
    )
    def broker_active(self) -> bool:
        """Checks ZooKeeper for client connections, checks for specific broker id.

        Args:
            unit: the `Unit` to check connection of
            zookeeper_config: the relation provided by ZooKeeper

        Returns:
            True if broker id is recognised as active by ZooKeeper. Otherwise False.
        """
        broker_id = self._local_unit.name.split("/")[1]
        brokers = self.get_active_brokers()
        chroot = self.zookeeper_config.get("chroot", "")
        return f"{chroot}/brokers/ids/{broker_id}" in brokers
