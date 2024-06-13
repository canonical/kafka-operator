#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Collection of state objects for the Kafka relations, apps and units."""

import logging

from charms.data_platform_libs.v0.data_interfaces import Data, DataPeerData, DataPeerUnitData
from charms.zookeeper.v0.client import QuorumLeaderNotFoundError, ZooKeeperManager
from kazoo.client import AuthFailedError, NoNodeError
from ops.model import Application, Relation, Unit
from tenacity import retry, retry_if_result, stop_after_attempt, wait_fixed
from typing_extensions import override

from literals import INTERNAL_USERS, SECRETS_APP, Substrates

logger = logging.getLogger(__name__)


class RelationState:
    """Relation state object."""

    def __init__(
        self,
        relation: Relation | None,
        data_interface: Data,
        component: Unit | Application | None,
        substrate: Substrates,
    ):
        self.relation = relation
        self.data_interface = data_interface
        self.component = (
            component  # FIXME: remove, and use _fetch_my_relation_data defaults wheren needed
        )
        self.substrate = substrate
        self.relation_data = (
            self.data_interface.as_dict(self.relation.id) if self.relation else {}
        )  # FIXME: mappingproxytype?

    def __bool__(self) -> bool:
        """Boolean evaluation based on the existence of self.relation."""
        try:
            return bool(self.relation)
        except AttributeError:
            return False

    def update(self, items: dict[str, str]) -> None:
        """Writes to relation_data."""
        delete_fields = [key for key in items if not items[key]]
        update_content = {k: items[k] for k in items if k not in delete_fields}

        self.relation_data.update(update_content)

        for field in delete_fields:
            del self.relation_data[field]


class KafkaCluster(RelationState):
    """State collection metadata for the peer relation."""

    def __init__(
        self,
        relation: Relation | None,
        data_interface: DataPeerData,
        component: Application,
        substrate: Substrates,
    ):
        super().__init__(relation, data_interface, component, substrate)
        self.data_interface = data_interface
        self.app = component

    @override
    def update(self, items: dict[str, str]) -> None:
        """Overridden update to allow for same interface, but writing to local app bag."""
        if not self.relation:
            return

        for key, value in items.items():
            # note: relation- check accounts for dynamically created secrets
            if key in SECRETS_APP or key.startswith("relation-"):
                if value:
                    self.data_interface.set_secret(self.relation.id, key, value)
                else:
                    self.data_interface.delete_secret(self.relation.id, key)
            else:
                self.data_interface.update_relation_data(self.relation.id, {key: value})

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


class KafkaBroker(RelationState):
    """State collection metadata for a unit."""

    def __init__(
        self,
        relation: Relation | None,
        data_interface: DataPeerUnitData,
        component: Unit,
        substrate: Substrates,
    ):
        super().__init__(relation, data_interface, component, substrate)
        self.data_interface = data_interface
        self.unit = component

    @property
    def unit_id(self) -> int:
        """The id of the unit from the unit name.

        e.g kafka/2 --> 2
        """
        return int(self.unit.name.split("/")[1])

    @property
    def host(self) -> str:
        """Return the hostname of a unit."""
        host = ""
        if self.substrate == "vm":
            for key in ["hostname", "ip", "private-address"]:
                if host := self.relation_data.get(key, ""):
                    break
        if self.substrate == "k8s":
            host = f"{self.unit.name.split('/')[0]}-{self.unit_id}.{self.unit.name.split('/')[0]}-endpoints"

        return host

    # --- TLS ---

    @property
    def private_key(self) -> str:
        """The unit private-key set during `certificates_joined`.

        Returns:
            String of key contents
            None if key not yet generated
        """
        return self.relation_data.get("private-key", "")

    @property
    def csr(self) -> str:
        """The unit cert signing request.

        Returns:
            String of csr contents
            None if csr not yet generated
        """
        return self.relation_data.get("csr", "")

    @property
    def certificate(self) -> str:
        """The signed unit certificate from the provider relation.

        Returns:
            String of cert contents in PEM format
            None if cert not yet generated/signed
        """
        return self.relation_data.get("certificate", "")

    @property
    def ca(self) -> str:
        """The ca used to sign unit cert.

        Returns:
            String of ca contents in PEM format
            None if cert not yet generated/signed
        """
        # defaults to ca for backwards compatibility after field change introduced with secrets
        return self.relation_data.get("ca-cert") or self.relation_data.get("ca", "")

    @property
    def keystore_password(self) -> str:
        """The unit keystore password set during `certificates_joined`.

        Returns:
            String of password
            None if password not yet generated
        """
        return self.relation_data.get("keystore-password", "")

    @property
    def truststore_password(self) -> str:
        """The unit truststore password set during `certificates_joined`.

        Returns:
            String of password
            None if password not yet generated
        """
        return self.relation_data.get("truststore-password", "")


class ZooKeeper(RelationState):
    """State collection metadata for a the Zookeeper relation."""

    def __init__(
        self,
        relation: Relation | None,
        data_interface: Data,
        substrate: Substrates,
        local_app: Application | None = None,
    ):
        super().__init__(relation, data_interface, None, substrate)
        self._local_app = local_app

    @property
    def username(self) -> str:
        """Username to connect to ZooKeeper."""
        if not self.relation:
            return ""

        return (
            self.data_interface.fetch_relation_field(
                relation_id=self.relation.id, field="username"
            )
            or ""
        )

    @property
    def password(self) -> str:
        """Password of the ZooKeeper user."""
        if not self.relation:
            return ""

        return (
            self.data_interface.fetch_relation_field(
                relation_id=self.relation.id, field="password"
            )
            or ""
        )

    @property
    def endpoints(self) -> str:
        """IP/host where ZooKeeper is located."""
        if not self.relation:
            return ""

        return (
            self.data_interface.fetch_relation_field(
                relation_id=self.relation.id, field="endpoints"
            )
            or ""
        )

    @property
    def database(self) -> str:
        """Path allocated for Kafka on ZooKeeper."""
        if not self.relation:
            return ""

        return (
            self.data_interface.fetch_relation_field(
                relation_id=self.relation.id, field="database"
            )
            or self.chroot
        )

    @property
    def chroot(self) -> str:
        """Path allocated for Kafka on ZooKeeper."""
        if not self.relation:
            return ""

        return (
            self.data_interface.fetch_relation_field(relation_id=self.relation.id, field="chroot")
            or ""
        )

    @property
    def uris(self) -> str:
        """Comma separated connection string, containing endpoints + chroot."""
        if not self.relation:
            return ""

        return (
            self.data_interface.fetch_relation_field(relation_id=self.relation.id, field="uris")
            or ""
        )

    @property
    def tls(self) -> bool:
        """Check if TLS is enabled on ZooKeeper."""
        if not self.relation:
            return False

        return (
            self.data_interface.fetch_relation_field(relation_id=self.relation.id, field="tls")
            or ""
        ) == "enabled"

    @property
    def connect(self) -> str:
        """Full connection string of sorted uris."""
        sorted_uris = sorted(self.uris.replace(self.database, "").split(","))
        sorted_uris[-1] = sorted_uris[-1] + self.database
        return ",".join(sorted_uris)

    @property
    def zookeeper_connected(self) -> bool:
        """Checks if there is an active ZooKeeper relation with all necessary data.

        Returns:
            True if ZooKeeper is currently related with sufficient relation data
                for a broker to connect with. Otherwise False
        """
        if not all([self.username, self.password, self.endpoints, self.database, self.uris]):
            return False

        return True

    @property
    def zookeeper_version(self) -> str:
        """Get running zookeeper version."""
        hosts = self.endpoints.split(",")
        zk = ZooKeeperManager(hosts=hosts, username=self.username, password=self.password)

        return zk.get_version()

    # retry to give ZK time to update its broker zNodes before failing
    @retry(
        wait=wait_fixed(5),
        stop=stop_after_attempt(10),
        retry=retry_if_result(lambda result: result is False),
        retry_error_callback=lambda _: False,
    )
    def broker_active(self) -> bool:
        """Checks if broker id is recognised as active by ZooKeeper."""
        broker_id = self.data_interface.local_unit.name.split("/")[1]
        hosts = self.endpoints.split(",")
        path = f"{self.database}/brokers/ids/"

        zk = ZooKeeperManager(hosts=hosts, username=self.username, password=self.password)
        try:
            brokers = zk.leader_znodes(path=path)
        except (NoNodeError, AuthFailedError, QuorumLeaderNotFoundError) as e:
            logger.debug(str(e))
            brokers = set()

        return f"{path}{broker_id}" in brokers


class KafkaClient(RelationState):
    """State collection metadata for a single related client application."""

    def __init__(
        self,
        relation: Relation | None,
        data_interface: Data,
        component: Application,
        substrate: Substrates,
        local_app: Application | None = None,
        bootstrap_server: str = "",
        password: str = "",  # nosec: B107
        tls: str = "",
        zookeeper_uris: str = "",
    ):
        super().__init__(relation, data_interface, component, substrate)
        self.app = component
        self._local_app = local_app
        self._bootstrap_server = bootstrap_server
        self._password = password
        self._tls = tls
        self._zookeeper_uris = zookeeper_uris

    @property
    def username(self) -> str:
        """The generated username for the client application."""
        return f"relation-{getattr(self.relation, 'id', '')}"

    @property
    def bootstrap_server(self) -> str:
        """The Kafka server endpoints for the client application to connect with."""
        return self._bootstrap_server

    @property
    def password(self) -> str:
        """The generated password for the client application."""
        return self._password

    @property
    def consumer_group_prefix(self) -> str:
        """The assigned consumer group prefix for a client application presenting consumer role."""
        return self.relation_data.get(
            "consumer-group-prefix",
            f"{self.username}-" if "consumer" in self.extra_user_roles else "",
        )

    @property
    def tls(self) -> str:
        """Flag to confirm whether or not ZooKeeper has TLS enabled.

        Returns:
            String of either 'enabled' or 'disabled'
        """
        return self._tls

    @property
    def zookeeper_uris(self) -> str:
        """The ZooKeeper connection endpoints for the client application to connect with."""
        return self._zookeeper_uris

    @property
    def topic(self) -> str:
        """The ZooKeeper connection endpoints for the client application to connect with."""
        return self.relation_data.get("topic", "")

    @property
    def extra_user_roles(self) -> str:
        """The client defined roles for their application.

        Can be any comma-delimited selection of `producer`, `consumer` and `admin`.
        When `admin` is set, the Kafka charm interprets this as a new super.user.
        """
        return self.relation_data.get("extra-user-roles", "")
