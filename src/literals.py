#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


"""Collection of globals common to the KafkaCharm."""

from dataclasses import dataclass
from typing import Dict, Literal

CHARM_KEY = "kafka"
PEER = "cluster"
ZK = "zookeeper"
REL_NAME = "kafka-client"
CHARM_USERS = ["sync"]
TLS_RELATION = "certificates"

AuthMechanism = Literal["SASL_PLAINTEXT", "SASL_SSL", "SSL"]
Scope = Literal["INTERNAL", "EXTERNAL"]


@dataclass
class Ports:
    external: int
    internal: int


SECURITY_PROTOCOL_PORTS: Dict[AuthMechanism, Ports] = {
    "SASL_PLAINTEXT": Ports(9092, 19092),
    "SASL_SSL": Ports(9093, 19093),
    "SSL": Ports(9094, 19094),
}
