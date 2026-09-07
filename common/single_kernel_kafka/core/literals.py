#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Collection of globals common to the KafkaCharm."""

import os
from dataclasses import dataclass
from enum import Enum
from typing import Literal, NamedTuple

import toml
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, StatusBase, WaitingStatus

# TODO: this logic should be replaced by `ops` API, whenever it supports it.
SUBSTRATE = os.environ.get("SUBSTRATE", "vm").replace("machine", "vm")
if SUBSTRATE not in ("vm", "k8s"):
    raise RuntimeError(f"Unknown substrate: {SUBSTRATE}")

CHARM_KEY = "kafka" if SUBSTRATE == "vm" else "kafka-k8s"

CONTAINER = "kafka"
STORAGE = "data"

SNAP_NAME = "charmed-kafka"
if SUBSTRATE == "vm":
    # '584792' refers to _daemon_, which do not exists on the storage-attached hook prior to the
    # snap install.
    # See https://snapcraft.io/docs/system-usernames.
    USER_ID = 584792
    USER_NAME = "_daemon_"
    GROUP = "root"
    # TODO: check if using `charm_refresh` internals is feasible for workload instead of these literals
    if os.path.exists("refresh_versions.toml"):
        with open("refresh_versions.toml", "r") as f:
            data = toml.load(f)

        SNAP_NAME = data["snap"]["name"]
        CHARMED_KAFKA_SNAP_REVISION = data["snap"]["revisions"]["x86_64"]
else:
    CHARMED_KAFKA_SNAP_REVISION = "-1"  # not used on K8s
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


class ConnectLiterals:
    """Kafka Connect specific literals."""

    DEFAULT_API_PORT = 8083
    DEFAULT_API_PROTOCOL = "http"
    DEFAULT_AUTH_CLASS = (
        "org.apache.kafka.connect.rest.basic.auth.extension.BasicAuthSecurityRestExtension"
    )
    DEFAULT_CONVERTER_CLASS = "org.apache.kafka.connect.json.JsonConverter"
    DEFAULT_SECURITY_MECHANISM = "SCRAM-SHA-512"
    GROUP_ID = "connect-cluster"

    SERVICE_NAME = "connect-distributed"
    PLUGIN_RESOURCE_KEY = "connect-plugin"
    JMX_EXPORTER_PORT = 9100
    METRICS_RULES_DIR = "./src/alert_rules/prometheus"
    EMPTY_PLUGIN_CHECKSUM = "84ff92691f909a05b224e1c56abb4864f01b4f8e3c854e4bb4c7baf1d3f6d652"

    TOPICS = {"offset": "connect-offset", "config": "connect-config", "status": "connect-status"}
    REPLICATION_FACTOR = -1  # -1 uses broker's default replication factor

    # NOTE: This key is used on a file to set the truststore password. The mirrormaker integrator charm
    # then points to this file to avoid sending the password over the API request config.
    TRUSTSTORE_PASSWORD_KEY = "truststore"

    # Relations
    KAFKA_CLIENT_REL = "kafka-client"
    PEER_REL = "worker"
    CLIENT_REL = "connect-client"
    TLS_REL = "certificates"

    CharmProfile = Literal["testing", "production"]
    ClientModes = Literal["worker", "producer", "consumer"]
    Converters = Literal["key", "value"]
    InternalTopics = Literal["offset", "config", "status"]


class TLSScope(str, Enum):
    """Enum for TLS scopes."""

    PEER = "peer"  # for internal communications
    CLIENT = "client"  # for external/client communications
    CONNECT = "connect"


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


if SUBSTRATE == "vm":
    PATHS = {
        "kafka": {
            "CONF": f"/var/snap/{SNAP_NAME}/current/etc/kafka",
            "LOGS": f"/var/snap/{SNAP_NAME}/common/var/log/kafka",
            "DATA": f"/var/snap/{SNAP_NAME}/common/var/lib/kafka",
            "BIN": f"/snap/{SNAP_NAME}/current/opt/kafka",
        },
        "cruise-control": {
            "CONF": f"/var/snap/{SNAP_NAME}/current/etc/cruise-control",
            "LOGS": f"/var/snap/{SNAP_NAME}/common/var/log/cruise-control",
            "DATA": f"/var/snap/{SNAP_NAME}/common/var/lib/cruise-control",
            "BIN": f"/snap/{SNAP_NAME}/current/opt/cruise-control",
        },
    }
else:
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
    """Charm role data model."""

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
    service="daemon" if SUBSTRATE == "vm" else "kafka",
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
    service="daemon" if SUBSTRATE == "vm" else "kafka",
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
    """Status object helper.

    The ``expectations`` and ``actions`` fields hold documentation prose
    for auto-generated pages. They are NOT used by the charm at runtime.
    A status with empty ``expectations`` and ``actions`` is
    automatically excluded from the docs table.

    Attributes:
        status: The ops status object (Active/Blocked/Waiting/Maintenance).
        log_level: The log level at which the status message is emitted.
        expectations: What this status means to the operator (docs only).
        actions: What the operator should do about it (docs only).
    """

    status: StatusBase
    log_level: DebugLevel
    expectations: str = ""
    actions: str = ""


class Status(Enum):
    """Collection of possible statuses for the charm."""

    ACTIVE = StatusLevel(
        ActiveStatus(),
        "DEBUG"
    )
    NO_PEER_RELATION = StatusLevel(
        MaintenanceStatus("no peer relation yet"), "DEBUG"
    )
    NO_PEER_CLUSTER_RELATION = StatusLevel(
        BlockedStatus("missing required peer-cluster relation"), "DEBUG"
    )
    SNAP_NOT_INSTALLED = StatusLevel(
        BlockedStatus(f"unable to install {SNAP_NAME} snap"),
        "ERROR",
        expectations=(
            "There are issues with the network connection and/or the snap Store"
        ),
        actions=(
            "Check your internet connection and Snapcraft.io status. Remove the "
            "application and when everything is OK, deploy the charm again"
        ),
    )
    SERVICE_NOT_RUNNING = StatusLevel(
        BlockedStatus("service not running"),
        "WARNING",
        expectations="The charm failed to start the Apache Kafka snap daemon processes",
        actions="Check the Apache Kafka logs for insights on the issue",
    )
    NOT_ALL_RELATED = StatusLevel(
        MaintenanceStatus("not all units related"), "DEBUG"
    )
    CC_NOT_RUNNING = StatusLevel(
        BlockedStatus("Cruise Control not running"),
        "WARNING",
        expectations="The charm failed to start the Cruise Control snap daemon process",
        actions="Check the Cruise Control logs for insights on the issue",
    )
    MISSING_MODE = StatusLevel(
        BlockedStatus("application needs to be related with a KRaft controller"),
        "DEBUG",
        expectations=(
            "The Apache Kafka brokers do not have information on where the KRaft "
            "controller to connect to is"
        ),
        actions=(
            "Ensure that there is an active relation between the broker and KRaft "
            "controllers, or that the broker application has configuration "
            "`roles=broker,controller`"
        ),
    )
    NO_CLUSTER_UUID = StatusLevel(
        WaitingStatus("waiting for cluster uuid"), "DEBUG"
    )
    NO_BOOTSTRAP_CONTROLLER = StatusLevel(
        WaitingStatus("waiting for bootstrap controller"), "DEBUG"
    )
    MISSING_CONTROLLER_PASSWORD = StatusLevel(
        WaitingStatus("waiting for controller user credentials"), "DEBUG"
    )
    BROKER_NOT_CONNECTED = StatusLevel(
        BlockedStatus("unit not connected to the controller"),
        "ERROR",
        expectations=(
            "The Apache Kafka broker unit is unable to authenticate to the KRaft "
            "controllers"
        ),
        actions=(
            "May self-resolve after 5-15m. Otherwise, check the Apache Kafka logs "
            "for insights on the issue"
        ),
    )
    ADDED_STORAGE = StatusLevel(
        ActiveStatus("manual partition reassignment may be needed to utilize new storage volumes"),
        "WARNING",
        expectations=(
            "Existing data is not automatically rebalanced when new storage is "
            "attached. New storage will be used for newly created topics and/or "
            "partitions"
        ),
        actions=(
            "Inspect the storage utilisation and based on the need, and rebalance "
            "data across multiple storages/brokers"
        ),
    )
    REMOVED_STORAGE = StatusLevel(
        ActiveStatus(
            "manual partition reassignment from replicated brokers recommended due to lost partitions on removed storage volumes"
        ),
        "ERROR",
        expectations=(
            "Storage volumes were removed from a broker that still has replicas "
            "elsewhere. Partitions that lived on the removed storage may be "
            "under-replicated until a rebalance is run."
        ),
        actions=(
            "Run a partition reassignment / rebalance to restore replication "
            "factors on the affected partitions."
        ),
    )
    REMOVED_STORAGE_NO_REPL = StatusLevel(
        ActiveStatus("potential data loss due to storage removal without replication"),
        "ERROR",
        expectations=(
            "Some partition/topics are not replicated on multiple storages, "
            "therefore potentially leading to data loss"
        ),
        actions=(
            "Add new storage, increase replication of topics/partitions and/or "
            "rebalance data across multiple storages/brokers"
        ),
    )
    NO_BROKER_CREDS = StatusLevel(
        WaitingStatus("internal broker credentials not yet added"),
        "DEBUG",
        expectations=(
            "Intrabroker credentials being created to enable communication and "
            "syncing among brokers belonging to the Apache Kafka clusters."
        ),
    )
    NO_CERT = StatusLevel(
        WaitingStatus("unit waiting for signed certificates"),
        "INFO",
        expectations=(
            "Unit has requested a CSR request via the certificates relation and "
            "it is waiting to receive the signed certificate"
        ),
    )
    NO_INTERNAL_TLS = StatusLevel(
        WaitingStatus("waiting for internal TLS setup"), "INFO"
    )
    NO_PEER_CLUSTER_CA = StatusLevel(
        WaitingStatus("waiting for peer-cluster TLS setup"), "INFO"
    )
    MTLS_REQUIRES_TLS = StatusLevel(
        BlockedStatus("can't setup mTLS client without a TLS relation first."),
        "ERROR",
        expectations=(
            "The units do not have the necessary client keystore and truststore "
            "to trust provided mTLS certificates"
        ),
        actions=(
            "Ensure that there is an active `certificates` relation with a "
            "`tls-certificates` relation interface provider application"
        ),
    )
    INVALID_CLIENT_CERTIFICATE = StatusLevel(
        BlockedStatus("mTLS client's certificate is not a valid leaf certificate."),
        "ERROR",
        expectations=(
            "The certificate provided in a `kafka_client` relation across the "
            "`mtls-cert` relation data field is not a valid certificate"
        ),
        actions=(
            "Ensure that the client application is sending a valid certificate, "
            "and not a CA"
        ),
    )
    SYSCONF_NOT_OPTIMAL = StatusLevel(
        ActiveStatus("machine system settings are not optimal - see logs for info"),
        "WARNING",
        expectations=(
            "The broker is running on a machine that has sub-optimal OS settings. "
            "Although this may not preclude Apache Kafka to work, it may result in "
            "sub-optimal performances"
        ),
        actions=(
            "Check the Juju debug-log for insights on which settings are "
            "sub-optimal and may be changed"
        ),
    )
    SYSCONF_NOT_POSSIBLE = StatusLevel(
        BlockedStatus("sysctl params cannot be set. Is the machine running on a container?"),
        "WARNING",
        expectations=(
            "Some of the sysctl settings required by Apache Kafka could not be "
            "set, therefore affecting Apache Kafka performance and correct "
            "settings. This can also be due to the charm being deployed on the "
            "wrong substrate"
        ),
        actions=(
            "Remove the deployment and make sure that the selected charm is "
            "correct given the Juju cloud substrate"
        ),
    )
    NOT_IMPLEMENTED = StatusLevel(
        BlockedStatus("feature not yet implemented"), "WARNING"
    )
    NO_BALANCER_RELATION = StatusLevel(
        MaintenanceStatus("no balancer relation yet"), "DEBUG"
    )
    NO_BROKER_DATA = StatusLevel(
        MaintenanceStatus("missing broker data"),
        "DEBUG",
        expectations=(
            "The KRaft controller or Cruise Control rebalancer does not have "
            "sufficient Apache Kafka broker data to make a valid connection"
        ),
        actions=(
            "Ensure that KRaft controller and/or Cruise Control rebalancer "
            "applications are related to a Apache Kafka broker application"
        ),
    )
    NOT_ENOUGH_BROKERS = StatusLevel(
        WaitingStatus(f"waiting for {MIN_REPLICAS} online brokers"),
        "DEBUG",
        expectations=(
            "The Cruise Control rebalancer application is not provided with the "
            "minimum number of brokers' data - 3"
        ),
        actions=(
            "Ensure that the Apache Kafka broker application has at least 3 units. "
            "Less than 3 units will result in Cruise Control not functioning"
        ),
    )
    WAITING_FOR_REBALANCE = StatusLevel(
        WaitingStatus("awaiting completion of rebalance task"),
        "DEBUG",
        expectations=(
            "The Cruise Control rebalancer application is currently running a "
            "rebalance task, and is busy"
        ),
    )
    SCALING_WARNING = StatusLevel(
        MaintenanceStatus(
            "Apache Kafka cluster is scaling, it is advised to postpone potentially disruptive actions like refresh."
        ),
        "WARNING",
        expectations=(
            "The Apache Kafka cluster is scaling. Potentially disruptive actions "
            "such as refresh should be postponed until scaling completes."
        ),
        actions="Wait for the scaling operation to complete.",
    )


class ConnectStatus(Enum):
    """Collection of possible statuses for the charm."""

    SNAP_NOT_INSTALLED = StatusLevel(BlockedStatus(f"unable to install {SNAP_NAME} snap"), "ERROR")
    INSTALLING = StatusLevel(MaintenanceStatus(f"installing {SNAP_NAME}"), "DEBUG")
    MISSING_KAFKA = StatusLevel(BlockedStatus("application needs Kafka client relation"), "DEBUG")
    NO_KAFKA_CREDENTIALS = StatusLevel(
        WaitingStatus("waiting for Kafka cluster credentials"), "DEBUG"
    )
    SERVICE_NOT_RUNNING = StatusLevel(BlockedStatus("worker service is not running"), "WARNING")
    SERVICE_STARTING = StatusLevel(WaitingStatus("worker is still starting up"), "INFO")
    SERVICE_UNHEALTHY = StatusLevel(BlockedStatus("worker is unable to handle requests"), "ERROR")
    NO_CERT = StatusLevel(WaitingStatus("unit waiting for signed certificates"), "INFO")

    ACTIVE = StatusLevel(ActiveStatus(), "DEBUG")


CONNECT_DEPENDENCIES = {
    "connect_service": {
        "dependencies": {},  # do not need to check Kafka, backwards compatible since 0.10
        "name": "connect",
        "upgrade_supported": ">=3.9",
        "version": "4.2.0",
    },
}
