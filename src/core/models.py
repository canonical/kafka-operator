#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Collection of state objects for the Kafka relations, apps and units."""

import json
import logging
from functools import cached_property
from typing import MutableMapping, TypeAlias, TypedDict

import requests
from charms.data_platform_libs.v0.data_interfaces import (
    PROV_SECRET_PREFIX,
    Data,
    DataPeerData,
    DataPeerUnitData,
)
from charms.zookeeper.v0.client import (
    NoUnitFoundError,
    QuorumLeaderNotFoundError,
    ZooKeeperManager,
)
from kazoo.client import AuthFailedError, ConnectionLoss, NoNodeError
from kazoo.exceptions import NoAuthError
from lightkube.resources.core_v1 import Node, Pod
from ops.model import Application, Relation, Unit
from tenacity import retry, retry_if_result, stop_after_attempt, wait_fixed
from typing_extensions import override

from literals import (
    BALANCER,
    BROKER,
    INTERNAL_USERS,
    SECRETS_APP,
    Substrates,
)
from managers.k8s import K8sManager

logger = logging.getLogger(__name__)

JSON: TypeAlias = dict[str, "JSON"] | list["JSON"] | str | int | float | bool | None


CPU = TypedDict("CPU", {"num.cores": str})
Capacity = TypedDict("Capacity", {"DISK": dict[str, str], "CPU": CPU, "NW_IN": str, "NW_OUT": str})
BrokerCapacity = TypedDict("BrokerCapacity", {"brokerId": str, "capacity": Capacity, "doc": str})
BrokerCapacities = TypedDict(
    "BrokerCapacities", {"brokerCapacities": list[BrokerCapacity]}, total=False
)


class RelationState:
    """Relation state object."""

    def __init__(
        self,
        relation: Relation | None,
        data_interface: Data,
        component: Unit | Application | None,
        substrate: Substrates | None = None,
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


class PeerCluster(RelationState):
    """State collection metadata for a peer-cluster application."""

    def __init__(
        self,
        relation: Relation | None,
        data_interface: Data,
        broker_username: str = "",
        broker_password: str = "",
        broker_uris: str = "",
        cluster_uuid: str = "",
        bootstrap_controller: str = "",
        bootstrap_unit_id: str = "",
        bootstrap_replica_id: str = "",
        racks: int = 0,
        broker_capacities: BrokerCapacities = {},
        zk_username: str = "",
        zk_password: str = "",
        zk_uris: str = "",
        balancer_username: str = "",
        balancer_password: str = "",
        balancer_uris: str = "",
        controller_password: str = "",
    ):
        super().__init__(relation, data_interface, None, None)
        self._broker_username = broker_username
        self._broker_password = broker_password
        self._broker_uris = broker_uris
        self._cluster_uuid = cluster_uuid
        self._bootstrap_controller = bootstrap_controller
        self._bootstrap_unit_id = bootstrap_unit_id
        self._bootstrap_replica_id = bootstrap_replica_id
        self._racks = racks
        self._broker_capacities = broker_capacities
        self._zk_username = zk_username
        self._zk_password = zk_password
        self._zk_uris = zk_uris
        self._balancer_username = balancer_username
        self._balancer_password = balancer_password
        self._balancer_uris = balancer_uris
        self._controller_password = controller_password

    def _fetch_from_secrets(self, group, field) -> str:
        if not self.relation:
            return ""

        if secrets_uri := self.relation.data[self.relation.app].get(
            f"{PROV_SECRET_PREFIX}{group}"
        ):
            if secret := self.data_interface._model.get_secret(id=secrets_uri):
                return secret.get_content().get(field, "")

        return ""

    @property
    def roles(self) -> str:
        """All the roles pass from the related application."""
        if not self.relation:
            return ""

        return (
            self.data_interface.fetch_relation_field(relation_id=self.relation.id, field="roles")
            or ""
        )

    @property
    def broker_username(self) -> str:
        """The provided username for the broker application."""
        if self._broker_username:
            return self._broker_username

        if not self.relation or not self.relation.app:
            return ""

        return self._fetch_from_secrets("broker", "broker-username")

    @property
    def broker_password(self) -> str:
        """The provided password for the broker application."""
        if self._broker_password:
            return self._broker_password

        if not self.relation or not self.relation.app:
            return ""

        return self._fetch_from_secrets("broker", "broker-password")

    @property
    def broker_uris(self) -> str:
        """The provided uris for the balancer application to connect to the broker application."""
        if self._broker_uris:
            return self._broker_uris

        if not self.relation or not self.relation.app:
            return ""

        return self.data_interface._fetch_relation_data_with_secrets(
            component=self.relation.app,
            req_secret_fields=BALANCER.requested_secrets,
            relation=self.relation,
            fields=BALANCER.requested_secrets,
        ).get("broker-uris", "")

    @property
    def controller_password(self) -> str:
        """The controller user password in KRaft mode."""
        if self._controller_password:
            return self._controller_password

        if not self.relation or not self.relation.app:
            return ""

        return self.data_interface._fetch_relation_data_with_secrets(
            component=self.relation.app,
            req_secret_fields=["controller-password"],
            relation=self.relation,
            fields=["controller-password"],
        ).get("controller-password", "")

    @property
    def cluster_uuid(self) -> str:
        """The cluster uuid used to format storages in KRaft mode."""
        if self._cluster_uuid:
            return self._cluster_uuid

        if not self.relation or not self.relation.app:
            return ""

        return (
            self.data_interface.fetch_relation_field(
                relation_id=self.relation.id, field="cluster-uuid"
            )
            or ""
        )

    @property
    def bootstrap_controller(self) -> str:
        """Bootstrap controller in KRaft mode."""
        if self._bootstrap_controller:
            return self._bootstrap_controller

        if not self.relation or not self.relation.app:
            return ""

        return (
            self.data_interface.fetch_relation_field(
                relation_id=self.relation.id, field="bootstrap-controller"
            )
            or ""
        )

    @property
    def bootstrap_unit_id(self) -> str:
        """Bootstrap unit ID in KRaft mode."""
        if self._bootstrap_unit_id:
            return self._bootstrap_unit_id

        if not self.relation or not self.relation.app:
            return ""

        return (
            self.data_interface.fetch_relation_field(
                relation_id=self.relation.id, field="bootstrap-unit-id"
            )
            or ""
        )

    @property
    def bootstrap_replica_id(self) -> str:
        """Directory ID of the bootstrap node in KRaft mode."""
        if self._bootstrap_replica_id:
            return self._bootstrap_replica_id

        if not self.relation or not self.relation.app:
            return ""

        return (
            self.data_interface.fetch_relation_field(
                relation_id=self.relation.id, field="bootstrap-replica-id"
            )
            or ""
        )

    @property
    def racks(self) -> int:
        """The number of racks for the brokers."""
        if self._racks:
            return self._racks

        if not self.relation:
            return 0

        return int(
            self.data_interface.fetch_relation_field(relation_id=self.relation.id, field="racks")
            or 0
        )

    @property
    def broker_capacities(self) -> BrokerCapacities:
        """The capacities for all Kafka brokers."""
        if self._broker_capacities:
            return self._broker_capacities

        if not self.relation:
            return {}

        return json.loads(
            self.data_interface.fetch_relation_field(
                relation_id=self.relation.id, field="broker-capacities"
            )
            or "{}"
        )

    @property
    def zk_username(self) -> str:
        """Username to connect to ZooKeeper."""
        if self._zk_username:
            return self._zk_username

        if not self.relation or not self.relation.app:
            return ""

        return self.data_interface._fetch_relation_data_with_secrets(
            component=self.relation.app,
            req_secret_fields=BALANCER.requested_secrets,
            relation=self.relation,
            fields=BALANCER.requested_secrets,
        ).get("zk-username", "")

    @property
    def zk_password(self) -> str:
        """Password to connect to ZooKeeper."""
        if self._zk_password:
            return self._zk_password

        if not self.relation or not self.relation.app:
            return ""

        return self.data_interface._fetch_relation_data_with_secrets(
            component=self.relation.app,
            req_secret_fields=BALANCER.requested_secrets,
            relation=self.relation,
            fields=BALANCER.requested_secrets,
        ).get("zk-password", "")

    @property
    def zk_uris(self) -> str:
        """The ZooKeeper server endpoints for the balancer application to connect with."""
        if self._zk_uris:
            return self._zk_uris

        if not self.relation or not self.relation.app:
            return ""

        return self.data_interface._fetch_relation_data_with_secrets(
            component=self.relation.app,
            req_secret_fields=BALANCER.requested_secrets,
            relation=self.relation,
            fields=BALANCER.requested_secrets,
        ).get("zk-uris", "")

    @property
    def balancer_username(self) -> str:
        """The provided username for the balancer application."""
        if self._balancer_username:
            return self._balancer_username

        if not self.relation or not self.relation.app:
            return ""

        return self.data_interface._fetch_relation_data_with_secrets(
            component=self.relation.app,
            req_secret_fields=BROKER.requested_secrets,
            relation=self.relation,
            fields=BALANCER.requested_secrets,
        ).get("balancer-username", "")

    @property
    def balancer_password(self) -> str:
        """The provided password for the balancer application."""
        if self._balancer_password:
            return self._balancer_password

        if not self.relation or not self.relation.app:
            return ""

        return self.data_interface._fetch_relation_data_with_secrets(
            component=self.relation.app,
            req_secret_fields=BROKER.requested_secrets,
            relation=self.relation,
            fields=BALANCER.requested_secrets,
        ).get("balancer-password", "")

    @property
    def balancer_uris(self) -> str:
        """The provided uris for the broker application to connect to the balancer application."""
        if self._balancer_uris:
            return self._balancer_uris

        if not self.relation or not self.relation.app:
            return ""

        return self.data_interface._fetch_relation_data_with_secrets(
            component=self.relation.app,
            req_secret_fields=BROKER.requested_secrets,
            relation=self.relation,
            fields=BALANCER.requested_secrets,
        ).get("balancer-uris", "")

    @property
    def broker_connected(self) -> bool:
        """Checks if there is an active broker relation with all necessary data."""
        # FIXME rename to specify balancer-broker connection
        if not all(
            [
                self.broker_username,
                self.broker_password,
                self.broker_uris,
                self.zk_username,
                self.zk_password,
                self.zk_uris,
                self.broker_capacities,
                # rack is optional, empty if not rack-aware
            ]
        ):
            return False

        return True

    @property
    def broker_connected_kraft_mode(self) -> bool:
        """Checks for necessary data required by a controller."""
        if not all([self.broker_username, self.broker_password, self.cluster_uuid]):
            return False

        return True


class KafkaCluster(RelationState):
    """State collection metadata for the peer relation."""

    def __init__(
        self,
        relation: Relation | None,
        data_interface: DataPeerData,
        component: Application,
    ):
        super().__init__(relation, data_interface, component, None)
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
    def controller_password(self) -> str:
        """The controller user password in KRaft mode."""
        return self.relation_data.get("controller-password", "")

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

    @property
    def balancer_username(self) -> str:
        """Persisted balancer username."""
        return self.relation_data.get("balancer-username", "")

    @property
    def balancer_password(self) -> str:
        """Persisted balancer password."""
        return self.relation_data.get("balancer-password", "")

    @property
    def balancer_uris(self) -> str:
        """Persisted balancer uris."""
        return self.relation_data.get("balancer-uris", "")

    @property
    def cluster_uuid(self) -> str:
        """Cluster uuid used for initializing storages."""
        return self.relation_data.get("cluster-uuid", "")

    @property
    def bootstrap_replica_id(self) -> str:
        """Directory ID of the bootstrap controller."""
        return self.relation_data.get("bootstrap-replica-id", "")

    @property
    def bootstrap_controller(self) -> str:
        """HOST:PORT address of the bootstrap controller."""
        return self.relation_data.get("bootstrap-controller", "")

    @property
    def bootstrap_unit_id(self) -> str:
        """Unit ID of the bootstrap controller."""
        return self.relation_data.get("bootstrap-unit-id", "")


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
        self.k8s = K8sManager(
            pod_name=self.pod_name,
            namespace=self.unit._backend.model_name,
        )

    @property
    def unit_id(self) -> int:
        """The id of the unit from the unit name.

        e.g kafka/2 --> 2
        """
        return int(self.unit.name.split("/")[1])

    @property
    def internal_address(self) -> str:
        """The address for internal communication between brokers."""
        addr = ""
        if self.substrate == "vm":
            for key in ["hostname", "ip", "private-address"]:
                if addr := self.relation_data.get(key, ""):
                    break

        if self.substrate == "k8s":
            addr = f"{self.unit.name.split('/')[0]}-{self.unit_id}.{self.unit.name.split('/')[0]}-endpoints"

        return addr

    # --- TLS ---

    @property
    def private_key(self) -> str:
        """The unit private-key set during `certificates_joined`.

        Returns:
            String of key contents
            Empty if key not yet generated
        """
        return self.relation_data.get("private-key", "")

    @property
    def csr(self) -> str:
        """The unit cert signing request.

        Returns:
            String of csr contents
            Empty if csr not yet generated
        """
        return self.relation_data.get("csr", "")

    @property
    def certificate(self) -> str:
        """The signed unit certificate from the provider relation.

        Returns:
            String of cert contents in PEM format
            Empty if cert not yet generated/signed
        """
        return self.relation_data.get("certificate", "")

    @property
    def ca(self) -> str:
        """The ca used to sign unit cert.

        Returns:
            String of ca contents in PEM format
            Empty if cert not yet generated/signed
        """
        # defaults to ca for backwards compatibility after field change introduced with secrets
        return self.relation_data.get("ca-cert") or self.relation_data.get("ca", "")

    @property
    def chain(self) -> list[str]:
        """The chain used to sign unit cert."""
        return json.loads(self.relation_data.get("chain", "null")) or []

    @property
    def bundle(self) -> list[str]:
        """The cert bundle used for TLS identity."""
        if not all([self.certificate, self.ca, self.chain]):
            return []

        # manual-tls-certificates is loaded with the signed cert, the intermediate CA that signed it
        # and then the missing chain for that CA
        # ZK needs to present the full bundle - aka Keystore
        # ZK needs to trust each item in the bundle - aka Truststore
        bundle = [self.certificate, self.ca] + self.chain
        return sorted(set(bundle), key=bundle.index)  # ordering might matter

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

    @property
    def storages(self) -> JSON:
        """The current Juju storages for the unit."""
        return json.loads(self.relation_data.get("storages", "{}"))

    @property
    def cores(self) -> str:
        """The number of CPU cores for the unit machine."""
        return self.relation_data.get("cores", "")

    @property
    def rack(self) -> str:
        """The rack for the broker on broker.rack from rack.properties."""
        return self.relation_data.get("rack", "")

    @property
    def pod_name(self) -> str:
        """The name of the K8s Pod for the unit.

        K8s-only.
        """
        return self.unit.name.replace("/", "-")

    @cached_property
    def pod(self) -> Pod:
        """The Pod of the unit.

        K8s-only.
        """
        return self.k8s.get_pod(self.pod_name)

    @cached_property
    def node(self) -> Node:
        """The Node the unit is scheduled on.

        K8s-only.
        """
        return self.k8s.get_node(self.pod_name)

    @cached_property
    def node_ip(self) -> str:
        """The IPV4/IPV6 IP address the Node the unit is on.

        K8s-only.
        """
        return self.k8s.get_node_ip(self.pod_name)

    @property
    def directory_id(self) -> str:
        """Directory ID of the node as saved in `meta.properties`."""
        return self.relation_data.get("directory-id", "")

    @property
    def added_to_quorum(self) -> bool:
        """Whether or not this node is added to dynamic quorum in KRaft mode."""
        return bool(self.relation_data.get("added-to-quorum", False))


class ZooKeeper(RelationState):
    """State collection metadata for a the Zookeeper relation."""

    def __init__(
        self,
        relation: Relation | None,
        data_interface: Data,
        local_app: Application | None = None,
    ):
        super().__init__(relation, data_interface, None, None)
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
    def hosts(self) -> list[str]:
        """Get the hosts from the databag."""
        return [host.split(":")[0] for host in self.endpoints.split(",")]

    @property
    def uris(self):
        """Comma separated connection string, containing endpoints + chroot."""
        return f"{self.endpoints.removesuffix('/')}/{self.database.removeprefix('/')}"

    @property
    def port(self) -> int:
        """Get the port in use from the databag.

        We can extract from:
        - host1:port,host2:port
        - host1,host2:port
        """
        try:
            port = next(
                iter([int(host.split(":")[1]) for host in reversed(self.endpoints.split(","))]),
                2181,
            )
        except IndexError:
            # compatibility with older zk versions
            port = 2181

        return port

    @property
    def zookeeper_version(self) -> str:
        """Get running zookeeper version."""
        zk = ZooKeeperManager(
            hosts=self.hosts,
            client_port=self.port,
            username=self.username,
            password=self.password,
            use_ssl=self.tls,
        )

        return zk.get_version()

    # retry to give ZK time to update its broker zNodes before failing
    @retry(
        wait=wait_fixed(3),
        stop=stop_after_attempt(3),
        retry=retry_if_result(lambda result: result is False),
        retry_error_callback=lambda _: False,
    )
    def broker_active(self) -> bool:
        """Checks if broker id is recognised as active by ZooKeeper."""
        broker_id = self.data_interface.local_unit.name.split("/")[1]
        path = f"{self.database}/brokers/ids/"
        try:
            zk = ZooKeeperManager(
                hosts=self.hosts,
                client_port=self.port,
                username=self.username,
                password=self.password,
                use_ssl=self.tls,
            )
            brokers = zk.leader_znodes(path=path)
        except (
            NoNodeError,
            AuthFailedError,
            QuorumLeaderNotFoundError,
            NoUnitFoundError,
            ConnectionLoss,
            NoAuthError,
        ) as e:
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
        local_app: Application | None = None,
        bootstrap_server: str = "",
        password: str = "",  # nosec: B107
        tls: str = "",
        zookeeper_uris: str = "",
    ):
        super().__init__(relation, data_interface, component, None)
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


class OAuth:
    """State collection metadata for the oauth relation."""

    def __init__(self, relation: Relation | None):
        self.relation = relation

    @property
    def relation_data(self) -> MutableMapping[str, str]:
        """Oauth relation data object."""
        if not self.relation or not self.relation.app:
            return {}

        return self.relation.data[self.relation.app]

    @property
    def issuer_url(self) -> str:
        """The issuer URL to identify the IDP."""
        return self.relation_data.get("issuer_url", "")

    @property
    def jwks_endpoint(self) -> str:
        """The JWKS endpoint needed to validate JWT tokens."""
        return self.relation_data.get("jwks_endpoint", "")

    @property
    def introspection_endpoint(self) -> str:
        """The introspection endpoint needed to validate non-JWT tokens."""
        return self.relation_data.get("introspection_endpoint", "")

    @property
    def jwt_access_token(self) -> bool:
        """A flag indicating if the access token is JWT or not."""
        return self.relation_data.get("jwt_access_token", "false").lower() == "true"

    @property
    def uses_trusted_ca(self) -> bool:
        """A flag indicating if the IDP uses certificates signed by a trusted CA."""
        try:
            requests.get(self.issuer_url, timeout=10)
            return True
        except requests.exceptions.SSLError:
            return False
        except requests.exceptions.RequestException:
            return True
