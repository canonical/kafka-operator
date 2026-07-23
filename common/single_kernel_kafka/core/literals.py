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
    """Status object helper."""

    status: StatusBase
    log_level: DebugLevel


class Status(Enum):
    """Collection of possible statuses for the charm.

    The possible ``# docs:`` comments prefixes (optional):

    * ``# docs:expectations:`` — what this status means to the operator
    * ``# docs:actions:``      — what the operator should do about it
    * ``# docs:hidden``        — suppress this status from the docs table
    """

    ACTIVE = StatusLevel(ActiveStatus(), "DEBUG")
    # docs:expectations: Normal charm operations
    # docs:actions: No actions required

    NO_PEER_RELATION = StatusLevel(MaintenanceStatus("no peer relation yet"), "DEBUG")
    # docs:hidden

    NO_PEER_CLUSTER_RELATION = StatusLevel(
        BlockedStatus("missing required peer-cluster relation"), "DEBUG"
    )
    # docs:hidden

    SNAP_NOT_INSTALLED = StatusLevel(BlockedStatus(f"unable to install {SNAP_NAME} snap"), "ERROR")
    # docs:expectations: There are issues with the network connection and/or the snap Store
    # docs:actions: Check your internet connection and Snapcraft.io status. Remove the
    # docs:actions: application and when everything is OK, deploy the charm again

    SERVICE_NOT_RUNNING = StatusLevel(BlockedStatus("service not running"), "WARNING")
    # docs:expectations: The charm failed to start the Apache Kafka snap daemon processes
    # docs:actions: Check the Apache Kafka logs for insights on the issue

    NOT_ALL_RELATED = StatusLevel(MaintenanceStatus("not all units related"), "DEBUG")
    # docs:hidden

    CC_NOT_RUNNING = StatusLevel(BlockedStatus("Cruise Control not running"), "WARNING")
    # docs:expectations: The charm failed to start the Cruise Control snap daemon process
    # docs:actions: Check the Cruise Control logs for insights on the issue

    MISSING_MODE = StatusLevel(
        BlockedStatus("application needs to be related with a KRaft controller"), "DEBUG"
    )
    # docs:expectations: The Apache Kafka brokers do not have information on where the KRaft
    # docs:expectations: controller to connect to is
    # docs:actions: Ensure that there is an active relation between the broker and KRaft
    # docs:actions: controllers, or that the broker application has configuration
    # docs:actions: `roles=broker,controller`

    NO_CLUSTER_UUID = StatusLevel(WaitingStatus("waiting for cluster uuid"), "DEBUG")
    # docs:hidden

    NO_BOOTSTRAP_CONTROLLER = StatusLevel(
        WaitingStatus("waiting for bootstrap controller"), "DEBUG"
    )
    # docs:hidden

    MISSING_CONTROLLER_PASSWORD = StatusLevel(
        WaitingStatus("waiting for controller user credentials"), "DEBUG"
    )
    # docs:hidden

    BROKER_NOT_CONNECTED = StatusLevel(
        BlockedStatus("unit not connected to the controller"), "ERROR"
    )
    # docs:expectations: The Apache Kafka broker unit is unable to authenticate to the KRaft
    # docs:expectations: controllers
    # docs:actions: May self-resolve after 5-15m. Otherwise, check the Apache Kafka logs
    # docs:actions: for insights on the issue

    ADDED_STORAGE = StatusLevel(
        ActiveStatus("manual partition reassignment may be needed to utilize new storage volumes"),
        "WARNING",
    )
    # docs:expectations: Existing data is not automatically rebalanced when new storage is
    # docs:expectations: attached. New storage will be used for newly created topics and/or
    # docs:expectations: partitions
    # docs:actions: Inspect the storage utilisation and based on the need, and rebalance
    # docs:actions: data across multiple storages/brokers

    REMOVED_STORAGE = StatusLevel(
        ActiveStatus(
            "manual partition reassignment from replicated brokers recommended due to lost partitions on removed storage volumes"
        ),
        "ERROR",
    )
    # docs:expectations: Storage volumes were removed from a broker that still has replicas
    # docs:expectations: elsewhere. Partitions that lived on the removed storage may be
    # docs:expectations: under-replicated until a rebalance is run.
    # docs:actions: Run a partition reassignment / rebalance to restore replication
    # docs:actions: factors on the affected partitions.

    REMOVED_STORAGE_NO_REPL = StatusLevel(
        ActiveStatus("potential data loss due to storage removal without replication"),
        "ERROR",
    )
    # docs:expectations: Some partition/topics are not replicated on multiple storages,
    # docs:expectations: therefore potentially leading to data loss
    # docs:actions: Add new storage, increase replication of topics/partitions and/or
    # docs:actions: rebalance data across multiple storages/brokers

    NO_BROKER_CREDS = StatusLevel(
        WaitingStatus("internal broker credentials not yet added"), "DEBUG"
    )
    # docs:expectations: Intrabroker credentials being created to enable communication and
    # docs:expectations: syncing among brokers belonging to the Apache Kafka clusters.
    # docs:actions:

    NO_CERT = StatusLevel(WaitingStatus("unit waiting for signed certificates"), "INFO")
    # docs:expectations: Unit has requested a CSR request via the certificates relation and
    # docs:expectations: it is waiting to receive the signed certificate
    # docs:actions:

    NO_INTERNAL_TLS = StatusLevel(WaitingStatus("waiting for internal TLS setup"), "INFO")
    # docs:hidden

    NO_PEER_CLUSTER_CA = StatusLevel(WaitingStatus("waiting for peer-cluster TLS setup"), "INFO")
    # docs:hidden

    MTLS_REQUIRES_TLS = StatusLevel(
        BlockedStatus("can't setup mTLS client without a TLS relation first."), "ERROR"
    )
    # docs:expectations: The units do not have the necessary client keystore and truststore
    # docs:expectations: to trust provided mTLS certificates
    # docs:actions: Ensure that there is an active `certificates` relation with a
    # docs:actions: `tls-certificates` relation interface provider application

    INVALID_CLIENT_CERTIFICATE = StatusLevel(
        BlockedStatus("mTLS client's certificate is not a valid leaf certificate."), "ERROR"
    )
    # docs:expectations: The certificate provided in a `kafka_client` relation across the
    # docs:expectations: `mtls-cert` relation data field is not a valid certificate
    # docs:actions: Ensure that the client application is sending a valid certificate,
    # docs:actions: and not a CA

    SYSCONF_NOT_OPTIMAL = StatusLevel(
        ActiveStatus("machine system settings are not optimal - see logs for info"),
        "WARNING",
    )
    # docs:expectations: The broker is running on a machine that has sub-optimal OS settings.
    # docs:expectations: Although this may not preclude Apache Kafka to work, it may result in
    # docs:expectations: sub-optimal performances
    # docs:actions: Check the Juju debug-log for insights on which settings are
    # docs:actions: sub-optimal and may be changed

    SYSCONF_NOT_POSSIBLE = StatusLevel(
        BlockedStatus("sysctl params cannot be set. Is the machine running on a container?"),
        "WARNING",
    )
    # docs:expectations: Some of the sysctl settings required by Apache Kafka could not be
    # docs:expectations: set, therefore affecting Apache Kafka performance and correct
    # docs:expectations: settings. This can also be due to the charm being deployed on the
    # docs:expectations: wrong substrate
    # docs:actions: Remove the deployment and make sure that the selected charm is
    # docs:actions: correct given the Juju cloud substrate

    NOT_IMPLEMENTED = StatusLevel(
        BlockedStatus("feature not yet implemented"),
        "WARNING",
    )
    # docs:hidden

    NO_BALANCER_RELATION = StatusLevel(MaintenanceStatus("no balancer relation yet"), "DEBUG")
    # docs:hidden

    NO_BROKER_DATA = StatusLevel(MaintenanceStatus("missing broker data"), "DEBUG")
    # docs:expectations: The KRaft controller or Cruise Control rebalancer does not have
    # docs:expectations: sufficient Apache Kafka broker data to make a valid connection
    # docs:actions: Ensure that KRaft controller and/or Cruise Control rebalancer
    # docs:actions: applications are related to a Apache Kafka broker application

    NOT_ENOUGH_BROKERS = StatusLevel(
        WaitingStatus(f"waiting for {MIN_REPLICAS} online brokers"), "DEBUG"
    )
    # docs:expectations: The Cruise Control rebalancer application is not provided with the
    # docs:expectations: minimum number of brokers' data - 3
    # docs:actions: Ensure that the Apache Kafka broker application has at least 3 units.
    # docs:actions: Less than 3 units will result in Cruise Control not functioning

    WAITING_FOR_REBALANCE = StatusLevel(
        WaitingStatus("awaiting completion of rebalance task"), "DEBUG"
    )
    # docs:expectations: The Cruise Control rebalancer application is currently running a
    # docs:expectations: rebalance task, and is busy
    # docs:actions:

    SCALING_WARNING = StatusLevel(
        MaintenanceStatus(
            "Apache Kafka cluster is scaling, it is advised to postpone potentially disruptive actions like refresh."
        ),
        "WARNING",
    )
    # docs:expectations: The Apache Kafka cluster is scaling. Potentially disruptive actions
    # docs:expectations: such as refresh should be postponed until scaling completes.
    # docs:actions: Wait for the scaling operation to complete.
