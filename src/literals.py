#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.


"""Collection of globals common to the KafkaCharm."""

from dataclasses import dataclass
from typing import Dict, Literal

from ops.model import ActiveStatus, BlockedStatus, StatusBase, WaitingStatus

CHARM_KEY = "kafka"
SNAP_NAME = "charmed-kafka"
NODE_EXPORTER_SNAP_NAME = "node-exporter"
PEER = "cluster"
ZK = "zookeeper"
REL_NAME = "kafka-client"
INTER_BROKER_USER = "sync"
ADMIN_USER = "admin"
TLS_RELATION = "certificates"
TRUSTED_CERTIFICATE_RELATION = "trusted-certificate"
TRUSTED_CA_RELATION = "trusted-ca"
INTERNAL_USERS = [INTER_BROKER_USER, ADMIN_USER]

AuthMechanism = Literal["SASL_PLAINTEXT", "SASL_SSL", "SSL"]
Scope = Literal["INTERNAL", "CLIENT"]


@dataclass
class Ports:
    client: int
    internal: int


SECURITY_PROTOCOL_PORTS: Dict[AuthMechanism, Ports] = {
    "SASL_PLAINTEXT": Ports(9092, 19092),
    "SASL_SSL": Ports(9093, 19093),
    "SSL": Ports(9094, 19094),
}

AvailableStatuses = Literal[
    "ACTIVE",
    "SNAP_NOT_INSTALLED",
    "ZK_NOT_RELATED",
    "ZK_NOT_CONNECTED",
    "SNAP_NOT_RUNNING",
    "ADDED_STORAGE",
    "REMOVED_STORAGE",
    "REMOVED_STORAGE_NO_REPL",
    "ZK_TLS_MISMATCH",
    "NO_PEER_RELATION",
    "ZK_NO_DATA",
    "NO_BROKER_CREDS",
]


STATUS: Dict[AvailableStatuses, StatusBase] = {
    "ACTIVE": ActiveStatus(),
    "NO_PEER_RELATION": WaitingStatus("no peer relation yet"),
    "SNAP_NOT_INSTALLED": BlockedStatus(f"unable to install {SNAP_NAME} snap"),
    "SNAP_NOT_RUNNING": BlockedStatus("snap service not running"),
    "ZK_NOT_RELATED": BlockedStatus("missing required zookeeper relation"),
    "ZK_NOT_CONNECTED": BlockedStatus("unit not connected to zookeeper"),
    "ZK_TLS_MISMATCH": BlockedStatus("tls must be enabled on both kafka and zookeeper"),
    "ZK_NO_DATA": WaitingStatus("zookeeper credentials not created yet"),
    "ADDED_STORAGE": ActiveStatus(
        "manual partition reassignment may be needed to utilize new storage volumes"
    ),
    "REMOVED_STORAGE": BlockedStatus(
        "manual partition reassignment from replicated brokers recommended due to lost partitions on removed storage volumes"
    ),
    "REMOVED_STORAGE_NO_REPL": BlockedStatus(
        "potential log-data loss due to storage removal without replication"
    ),
    "NO_BROKER_CREDS": WaitingStatus("internal broker credentials not yet added"),
}
