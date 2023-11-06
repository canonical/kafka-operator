"""Module with all domain specific objects used by the charm."""

from dataclasses import dataclass
from enum import Enum
from typing import List
from typing import Sequence
from typing import Set

from ops import WaitingStatus
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus

from literals import SECURITY_PROTOCOL_PORTS
from literals import SNAP_NAME
from structured_config import CharmConfig as BaseKafkaConfig


class Status(Enum):
    ACTIVE = ActiveStatus()
    NO_PEER_RELATION = MaintenanceStatus("no peer relation yet")
    SNAP_NOT_INSTALLED = BlockedStatus(f"unable to install {SNAP_NAME} snap")
    SNAP_NOT_RUNNING = BlockedStatus("snap service not running")
    ZK_NOT_RELATED = BlockedStatus("missing required zookeeper relation")
    ZK_NOT_CONNECTED = BlockedStatus("unit not connected to zookeeper")
    ZK_TLS_MISMATCH = BlockedStatus("tls must be enabled on both kafka and zookeeper")
    ZK_NO_DATA = WaitingStatus("zookeeper credentials not created yet")
    ADDED_STORAGE = ActiveStatus(
        "manual partition reassignment may be needed to utilize new storage volumes"
    )
    REMOVED_STORAGE = ActiveStatus(
        "manual partition reassignment from replicated brokers recommended due to lost "
        "partitions on removed storage volumes"
    )
    REMOVED_STORAGE_NO_REPL = ActiveStatus("potential data loss due to storage removal without "
                                           "replication")
    NO_BROKER_CREDS = WaitingStatus("internal broker credentials not yet added")
    NO_CERT = WaitingStatus("unit waiting for signed certificates")
    SYSCONF_NOT_OPTIMAL = ActiveStatus("machine system settings are not optimal "
                                       "- see logs for info")
    SYSCONF_NOT_POSSIBLE = BlockedStatus("sysctl params cannot be set. Is the machine running on "
                                         "a container?")


@dataclass
class ZookeeperConfig:
    username: str
    password: str
    chroot: str
    connect: str
    uri: str
    tls: bool

    @property
    def connected(self) -> bool:
        """Checks if there is an active ZooKeeper relation with all necessary data.

        Returns:
            True if ZooKeeper is currently related with sufficient relation data
                for a broker to connect with. Otherwise False
        """
        if self.connect:
            return True

        return False


@dataclass
class TLSConfig:
    enabled: bool = False
    mtls_enabled: bool = False
    private_key: str | None = None
    csr: str | None = None
    ca: str | None = None
    certificate: str | None = None
    keystore_password: str | None = None
    truststore_password: str | None = None


@dataclass
class Broker:
    unit: int
    host: str
    address: str | None = None


@dataclass
class ClusterRelation:
    unit: Broker
    hosts: Sequence[Broker]
    internal_user_credentials: dict[str, str]
    tls: TLSConfig

    @property
    def bootstrap_servers(self) -> List[str]:
        port = (
            SECURITY_PROTOCOL_PORTS["SASL_SSL"].client
            if (self.tls.enabled and self.tls.certificate)
            else SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT"].client
        )
        return [f"{host.host}:{port}" for host in self.hosts]


@dataclass
class KafkaClient:
    username: str
    password: str
    extra_user_roles: Set[str]

    def copy(
            self, username: str | None = None,
            password: str | None = None,
            extra_user_roles: Set[str] | None = None
    ):
        return KafkaClient(
            username=username if username else self.username,
            password=password if password else self.password,
            extra_user_roles=extra_user_roles if extra_user_roles is not None \
                else self.extra_user_roles
        )


class UpgradeRelation:
    current_version: str

    @property
    def major_minor(self) -> str:
        major_minor = self.current_version.split(".", maxsplit=2)
        return ".".join(major_minor[:2])


@dataclass
class Storage:
    location: str


class KafkaConfig(BaseKafkaConfig):
    planned_units: int
    storages: dict[str, List[Storage]]


@dataclass
class CharmState:
    config: KafkaConfig | None = None
    cluster: ClusterRelation | None = None
    upgrade: UpgradeRelation | None = None
    zookeeper: ZookeeperConfig | None = None
    clients: dict[int, KafkaClient] = {}

    @property
    def ready_to_start(self) -> bool:
        """Check for active ZooKeeper relation and adding of inter-broker auth username.

        Returns:
            True if ZK is related and `sync` user has been added. False otherwise.
        """
        return self.compute_status() == Status.ACTIVE

    def compute_status(self) -> Status:
        if not self.cluster:
            return Status.NO_PEER_RELATION

        if not self.zookeeper:
            return Status.ZK_NOT_RELATED

        if not self.zookeeper.connect:
            return Status.ZK_NO_DATA

        # TLS must be enabled for Kafka and ZK or disabled for both
        if self.cluster.tls.enabled ^ self.zookeeper.tls:
            return Status.ZK_TLS_MISMATCH

        if not self.cluster.internal_user_credentials:
            return Status.NO_BROKER_CREDS

        return Status.ACTIVE