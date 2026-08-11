#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from pathlib import Path

import yaml
from common.single_kernel_kafka.core.literals import ConnectLiterals
from common.single_kernel_kafka.workload import ConnectPaths

from ..helpers import SUBSTRATE, SUBSTRATE_CLS

if SUBSTRATE == "vm":
    from connect_machine.src.charm import ConnectCharm
else:
    from connect_k8s.src.charm import ConnectCharm

_charm_cls = ConnectCharm
_substrate_cls = SUBSTRATE_CLS
CLIENT_REL = ConnectLiterals.CLIENT_REL
KAFKA_CLIENT_REL = ConnectLiterals.KAFKA_CLIENT_REL
PEER_REL = ConnectLiterals.PEER_REL
PLUGIN_PATH = ConnectPaths.MACHINE["plugins"] if SUBSTRATE == "vm" else ConnectPaths.K8S["plugins"]
TLS_REL = ConnectLiterals.TLS_REL

CONFIG = yaml.safe_load(Path(f"./connect_{SUBSTRATE_CLS.lower()}/config.yaml").read_text())
ACTIONS = yaml.safe_load(Path(f"./connect_{SUBSTRATE_CLS.lower()}/actions.yaml").read_text())
METADATA = yaml.safe_load(Path(f"./connect_{SUBSTRATE_CLS.lower()}/metadata.yaml").read_text())
