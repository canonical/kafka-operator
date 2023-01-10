#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


"""Collection of globals common to the KafkaCharm."""

CHARM_KEY = "kafka"
PEER = "cluster"
ZK = "zookeeper"
REL_NAME = "kafka-client"
CHARM_USERS = ["sync"]
TLS_RELATION = "certificates"

SECURITY_PROTOCOL_PORTS = {
    "SASL_PLAINTEXT": (9092, 19092),
    "SASL_SSL": (9093, 19093),
    "SSL": (9094, 19094),
}
