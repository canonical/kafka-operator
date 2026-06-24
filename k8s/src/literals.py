#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Collection of globals common to the KafkaCharm."""

from dataclasses import dataclass
from enum import Enum
from typing import Literal, NamedTuple

from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, StatusBase, WaitingStatus

CHARM_KEY = "kafka-k8s"
SNAP_NAME = "charmed-kafka"
CONTAINER = "kafka"
SUBSTRATE = "k8s"
STORAGE = "data"

USER_ID = "kafka"
USER_NAME = "kafka"
GROUP = "kafka"

# FIXME: these need better names
PEER = "cluster"
REL_NAME = "kafka-client"
OAUTH_REL_NAME = "oauth"

TLS_RELATION = "certificates"
INTERNAL_TLS_RELATION = "peer-certificates"
CERTIFICATE_TRANSFER_RELATION = "client-cas"
PEER_CLUSTER_RELATION = "peer-cluster"
PEER_CLUSTER_ORCHESTRATOR_RELATION = "peer-cluster-orchestrator"
BALANCER_TOPICS = [
    "__CruiseControlMetrics",
    "__KafkaCruiseControlPartitionMetricSamples",
    "__KafkaCruiseControlBrokerMetricSamples",
]
MIN_REPLICAS = 3
KRAFT_VERSION = 1


class TLSScope(str, Enum):
    """Enum for TLS scopes."""

    PEER = "peer"  # for internal communications
    CLIENT = "client"  # for external/client communications


INTER_BROKER_USER = "replication"
ADMIN_USER = "operator"
CONTROLLER_USER = "controller"
BALANCER_WEBSERVER_USER = "balancer"
INTERNAL_USERS = [INTER_BROKER_USER, ADMIN_USER]
BALANCER_WEBSERVER_PORT = 9090

SECRETS_APP = [
    f"{user}-password" for user in INTERNAL_USERS + [BALANCER_WEBSERVER_USER, CONTROLLER_USER]
] + ["internal-ca", "internal-ca-key"]
SECRETS_UNIT = [
    "truststore-password",
    "keystore-password",
    "client-ca-cert",
    "client-certificate",
    "client-chain",
    "client-csr",
    "client-private-key",
    "peer-ca-cert",
    "peer-certificate",
    "peer-chain",
    "peer-csr",
    "peer-private-key",
]

JMX_EXPORTER_PORT = 9101
JMX_CC_PORT = 9102
METRICS_RULES_DIR = "./src/alert_rules/prometheus"
LOGS_RULES_DIR = "./src/alert_rules/loki"


@dataclass
class Ports:
    """Types of ports for a Kafka broker."""

    client: int
    internal: int
    external: int
    controller: int
    extra: int = 0


AuthProtocol = Literal["SASL_PLAINTEXT", "SASL_SSL", "SSL"]
AuthMechanism = Literal["SCRAM-SHA-512", "OAUTHBEARER", "SSL"]
Scope = Literal["INTERNAL", "CLIENT", "EXTERNAL", "EXTRA", "CONTROLLER"]
AuthMap = NamedTuple("AuthMap", protocol=AuthProtocol, mechanism=AuthMechanism)

SECURITY_PROTOCOL_PORTS: dict[AuthMap, Ports] = {
    AuthMap("SASL_PLAINTEXT", "SCRAM-SHA-512"): Ports(9092, 19092, 29092, 9097),
    AuthMap("SASL_SSL", "SCRAM-SHA-512"): Ports(9093, 19093, 29093, 9098),
    AuthMap("SSL", "SSL"): Ports(9094, 19094, 29094, 19194),
    AuthMap("SASL_PLAINTEXT", "OAUTHBEARER"): Ports(9095, 19095, 29095, 19195),
    AuthMap("SASL_SSL", "OAUTHBEARER"): Ports(9096, 19096, 29096, 19196),
}

# FIXME: when running broker node.id will be unit-id + 100. If unit is only running
# the controller node.id == unit-id. This way we can keep a human readable mapping of ids.
KRAFT_NODE_ID_OFFSET = 100

DebugLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
DatabagScope = Literal["unit", "app"]
Substrates = Literal["vm", "k8s"]

JVM_MEM_MIN_GB = 1
JVM_MEM_MAX_GB = 6
OS_REQUIREMENTS = {
    "vm.max_map_count": "262144",
    "vm.swappiness": "1",
    "vm.dirty_ratio": "80",
    "vm.dirty_background_ratio": "5",
}


PATHS = {
    "kafka": {
        "CONF": "/etc/kafka",
        "LOGS": "/var/log/kafka",
        "DATA": "/var/lib/kafka",
        "BIN": "/opt/kafka",
    },
    "cruise-control": {
        "CONF": "/etc/cruise-control",
        "LOGS": "/var/log/cruise-control",
        "DATA": "/var/lib/cruise-control",
        "BIN": "/opt/cruise-control",
    },
}


@dataclass
class Role:
    value: str
    service: str
    paths: dict[str, str]
    relation: str
    requested_secrets: list[str]

    def __eq__(self, value: object, /) -> bool:
        """Provide an easy comparison to the configuration key."""
        return self.value == value


BROKER = Role(
    value="broker",
    service="kafka",
    paths=PATHS["kafka"],
    relation=PEER_CLUSTER_ORCHESTRATOR_RELATION,
    requested_secrets=[
        "balancer-username",
        "balancer-password",
        "balancer-uris",
        "controller-password",
    ],
)
CONTROLLER = Role(
    value="controller",
    service="daemon",
    paths=PATHS["kafka"],
    relation=PEER_CLUSTER_RELATION,
    requested_secrets=[
        "broker-username",
        "broker-password",
        "controller-password",
    ],
)
BALANCER = Role(
    value="balancer",
    service="cruise-control",
    paths=PATHS["cruise-control"],
    relation=PEER_CLUSTER_RELATION,
    requested_secrets=[
        "broker-username",
        "broker-password",
        "broker-uris",
        "controller-passwrod",
        "zk-username",
        "zk-password",
        "zk-uris",
    ],
)

DEFAULT_BALANCER_GOALS = [
    "ReplicaCapacity",
    "DiskCapacity",
    "NetworkInboundCapacity",
    "NetworkOutboundCapacity",
    "CpuCapacity",
    "ReplicaDistribution",
    "PotentialNwOut",
    "DiskUsageDistribution",
    "NetworkInboundUsageDistribution",
    "NetworkOutboundUsageDistribution",
    "CpuUsageDistribution",
    "LeaderReplicaDistribution",
    "LeaderBytesInDistribution",
    "TopicReplicaDistribution",
    "PreferredLeaderElection",
]
HARD_BALANCER_GOALS = [
    "ReplicaCapacity",
    "DiskCapacity",
    "NetworkInboundCapacity",
    "NetworkOutboundCapacity",
    "CpuCapacity",
    "ReplicaDistribution",
]
BALANCER_GOALS_TESTING = ["ReplicaDistribution"]


MODE_FULL = "full"
MODE_ADD = "add"
MODE_REMOVE = "remove"

PROFILE_TESTING = "testing"


class KRaftUnitStatus(str, Enum):
    """KRaft unit status (also known as role) in KRaft Quorums."""

    LEADER = "Leader"
    FOLLOWER = "Follower"
    OBSERVER = "Observer"


@dataclass
class KRaftQuorumInfo:
    """Object containing Quorum info for a KRaft controller."""

    directory_id: str
    lag: int
    status: KRaftUnitStatus


@dataclass
class StatusLevel:
    """Status object helper."""

    status: StatusBase
    log_level: DebugLevel


class Status(Enum):
    """Collection of possible statuses for the charm."""

    ACTIVE = StatusLevel(ActiveStatus(), "DEBUG")
    NO_PEER_RELATION = StatusLevel(MaintenanceStatus("no peer relation yet"), "DEBUG")
    NO_PEER_CLUSTER_RELATION = StatusLevel(
        BlockedStatus("missing required peer-cluster relation"), "DEBUG"
    )
    SNAP_NOT_INSTALLED = StatusLevel(BlockedStatus(f"unable to install {SNAP_NAME} snap"), "ERROR")
    SERVICE_NOT_RUNNING = StatusLevel(BlockedStatus("service not running"), "WARNING")
    NOT_ALL_RELATED = StatusLevel(MaintenanceStatus("not all units related"), "DEBUG")
    CC_NOT_RUNNING = StatusLevel(BlockedStatus("Cruise Control not running"), "WARNING")
    MISSING_MODE = StatusLevel(
        BlockedStatus("application needs to be related with a KRaft controller"), "DEBUG"
    )
    NO_CLUSTER_UUID = StatusLevel(WaitingStatus("waiting for cluster uuid"), "DEBUG")
    NO_BOOTSTRAP_CONTROLLER = StatusLevel(
        WaitingStatus("waiting for bootstrap controller"), "DEBUG"
    )
    MISSING_CONTROLLER_PASSWORD = StatusLevel(
        WaitingStatus("waiting for controller user credentials"), "DEBUG"
    )
    BROKER_NOT_CONNECTED = StatusLevel(
        BlockedStatus("unit not connected to the controller"), "ERROR"
    )
    ADDED_STORAGE = StatusLevel(
        ActiveStatus("manual partition reassignment may be needed to utilize new storage volumes"),
        "WARNING",
    )
    REMOVED_STORAGE = StatusLevel(
        ActiveStatus(
            "manual partition reassignment from replicated brokers recommended due to lost partitions on removed storage volumes"
        ),
        "ERROR",
    )
    REMOVED_STORAGE_NO_REPL = StatusLevel(
        ActiveStatus("potential data loss due to storage removal without replication"),
        "ERROR",
    )
    NO_BROKER_CREDS = StatusLevel(
        WaitingStatus("internal broker credentials not yet added"), "DEBUG"
    )
    NO_CERT = StatusLevel(WaitingStatus("unit waiting for signed certificates"), "INFO")
    NO_INTERNAL_TLS = StatusLevel(WaitingStatus("waiting for internal TLS setup"), "INFO")
    NO_PEER_CLUSTER_CA = StatusLevel(WaitingStatus("waiting for peer-cluster TLS setup"), "INFO")
    MTLS_REQUIRES_TLS = StatusLevel(
        BlockedStatus("can't setup mTLS client without a TLS relation first."), "ERROR"
    )
    INVALID_CLIENT_CERTIFICATE = StatusLevel(
        BlockedStatus("mTLS client's certificate is not a valid leaf certificate."), "ERROR"
    )
    SYSCONF_NOT_OPTIMAL = StatusLevel(
        ActiveStatus("machine system settings are not optimal - see logs for info"),
        "WARNING",
    )
    SYSCONF_NOT_POSSIBLE = StatusLevel(
        BlockedStatus("sysctl params cannot be set. Is the machine running on a container?"),
        "WARNING",
    )
    NOT_IMPLEMENTED = StatusLevel(
        BlockedStatus("feature not yet implemented"),
        "WARNING",
    )
    NO_BALANCER_RELATION = StatusLevel(MaintenanceStatus("no balancer relation yet"), "DEBUG")
    NO_BROKER_DATA = StatusLevel(MaintenanceStatus("missing broker data"), "DEBUG")
    NOT_ENOUGH_BROKERS = StatusLevel(
        WaitingStatus(f"waiting for {MIN_REPLICAS} online brokers"), "DEBUG"
    )
    WAITING_FOR_REBALANCE = StatusLevel(
        WaitingStatus("awaiting completion of rebalance task"), "DEBUG"
    )
    SCALING_WARNING = StatusLevel(
        MaintenanceStatus(
            "Apache Kafka cluster is scaling, it is advised to postpone potentially disruptive actions like refresh."
        ),
        "WARNING",
    )
