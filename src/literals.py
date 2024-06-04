#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Collection of globals common to the KafkaCharm."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal

from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, StatusBase, WaitingStatus

CHARM_KEY = "kafka"
SNAP_NAME = "charmed-kafka"
CHARMED_KAFKA_SNAP_REVISION = 37
CONTAINER = "kafka"
SUBSTRATE = "vm"

USER = "snap_daemon"
GROUP = "root"

# FIXME: these need better names
PEER = "cluster"
ZK = "zookeeper"
REL_NAME = "kafka-client"
TLS_RELATION = "certificates"
TRUSTED_CERTIFICATE_RELATION = "trusted-certificate"
TRUSTED_CA_RELATION = "trusted-ca"

INTER_BROKER_USER = "sync"
ADMIN_USER = "admin"
INTERNAL_USERS = [INTER_BROKER_USER, ADMIN_USER]
SECRETS_APP = [f"{user}-password" for user in INTERNAL_USERS]
SECRETS_UNIT = [
    "ca-cert",
    "csr",
    "certificate",
    "truststore-password",
    "keystore-password",
    "private-key",
]

JMX_EXPORTER_PORT = 9101
METRICS_RULES_DIR = "./src/alert_rules/prometheus"
LOGS_RULES_DIR = "./src/alert_rules/loki"

SUBSTRATE = "vm"
# '584788' refers to snap_daemon, which do not exists on the storage-attached hook prior to the
# snap install.
# FIXME (24.04): From snapd 2.61 onwards, snap_daemon is being deprecated and replaced with _daemon_,
# which now possesses a UID of 584792.
# See https://snapcraft.io/docs/system-usernames.
USER = 584788
GROUP = "root"

AuthMechanism = Literal["SASL_PLAINTEXT", "SASL_SSL", "SSL"]
Scope = Literal["INTERNAL", "CLIENT"]
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
    "CONF": Path(f"/var/snap/{SNAP_NAME}/current/etc"),
    "LOGS": Path(f"/var/snap/{SNAP_NAME}/common/var/log"),
    "DATA": Path(f"/var/snap/{SNAP_NAME}/common/var/lib"),
    "BIN": Path(f"/snap/{SNAP_NAME}/current/opt"),
}


@dataclass
class Ports:
    """Types of ports for a Kafka broker."""

    client: int
    internal: int


SECURITY_PROTOCOL_PORTS: dict[AuthMechanism, Ports] = {
    "SASL_PLAINTEXT": Ports(9092, 19092),
    "SASL_SSL": Ports(9093, 19093),
    "SSL": Ports(9094, 19094),
}


@dataclass
class StatusLevel:
    """Status object helper."""

    status: StatusBase
    log_level: DebugLevel


class Status(Enum):
    """Collection of possible statuses for the charm."""

    ACTIVE = StatusLevel(ActiveStatus(), "DEBUG")
    NO_PEER_RELATION = StatusLevel(MaintenanceStatus("no peer relation yet"), "DEBUG")
    SNAP_NOT_INSTALLED = StatusLevel(BlockedStatus(f"unable to install {SNAP_NAME} snap"), "ERROR")
    SNAP_NOT_RUNNING = StatusLevel(BlockedStatus("snap service not running"), "WARNING")
    ZK_NOT_RELATED = StatusLevel(BlockedStatus("missing required zookeeper relation"), "DEBUG")
    ZK_NOT_CONNECTED = StatusLevel(BlockedStatus("unit not connected to zookeeper"), "ERROR")
    ZK_TLS_MISMATCH = StatusLevel(
        BlockedStatus("tls must be enabled on both kafka and zookeeper"), "ERROR"
    )
    ZK_NO_DATA = StatusLevel(WaitingStatus("zookeeper credentials not created yet"), "DEBUG")
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


DEPENDENCIES = {
    "kafka_service": {
        "dependencies": {"zookeeper": "^3.6"},
        "name": "kafka",
        "upgrade_supported": ">3",
        "version": "3.6.1",
    },
}


class Role(str, Enum):
    BROKER = "broker"
    PARTITIONER = "partitioner"


class Service(str, Enum):
    BROKER = "daemon"
    PARTIONER = "cruise-control"
