#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
import json
import logging
import socket
from pathlib import Path
from typing import cast
from unittest.mock import PropertyMock, patch

import pytest
import trustme
import yaml
from ops.testing import Container, Context, PeerRelation, State
from trustme import CA

from charm import KafkaCharm
from literals import (
    CHARM_KEY,
    CONTAINER,
    PEER,
    SUBSTRATE,
)

pytestmark = pytest.mark.broker


logger = logging.getLogger(__name__)


CONFIG = yaml.safe_load(Path("./config.yaml").read_text())
ACTIONS = yaml.safe_load(Path("./actions.yaml").read_text())
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())


@pytest.fixture()
def ca() -> CA:
    return trustme.CA()


@pytest.fixture()
def base_state():
    if SUBSTRATE == "k8s":
        state = State(leader=True, containers=[Container(name=CONTAINER, can_connect=True)])

    else:
        state = State(leader=True)

    return state


@pytest.fixture()
def charm_configuration():
    """Enable direct mutation on configuration dict."""
    return json.loads(json.dumps(CONFIG))


@pytest.fixture()
def ctx() -> Context:
    ctx = Context(KafkaCharm, meta=METADATA, config=CONFIG, actions=ACTIONS, unit_id=0)
    return ctx


@pytest.mark.parametrize(
    ["config_option", "extra_sans", "expected"],
    [
        ("certificate_extra_sans", "", []),
        ("certificate_extra_sans", "worker{unit}.com", ["worker0.com"]),
        (
            "certificate_extra_sans",
            "worker{unit}.com,{unit}.example",
            ["worker0.com", "0.example"],
        ),
        (
            "extra_listeners",
            "run{unit}.shadowfax:30000,{unit}.proudfoot:40000,fool.ofa.took:45000,no.port.{unit}.com",
            ["run0.shadowfax", "0.proudfoot", "fool.ofa.took", "no.port.0.com"],
        ),
    ],
)
def test_extra_sans_config(
    charm_configuration: dict,
    base_state: State,
    config_option: str,
    extra_sans: str,
    expected: list[str],
) -> None:
    # Given
    charm_configuration["options"][config_option]["default"] = extra_sans
    cluster_peer = PeerRelation(
        PEER,
        PEER,
        local_unit_data={"private-address": "treebeard"},
    )
    state_in = dataclasses.replace(base_state, relations=[cluster_peer])
    ctx = Context(
        KafkaCharm, meta=METADATA, config=charm_configuration, actions=ACTIONS, unit_id=0
    )

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)

        # Then
        assert charm.broker.tls_manager._build_extra_sans() == expected


def test_sans(charm_configuration: dict, base_state: State, patched_node_ip) -> None:
    # Given
    charm_configuration["options"]["certificate_extra_sans"]["default"] = "worker{unit}.com"
    cluster_peer = PeerRelation(
        PEER,
        PEER,
        local_unit_data={"private-address": "treebeard"},
    )
    state_in = dataclasses.replace(base_state, relations=[cluster_peer])
    ctx = Context(
        KafkaCharm, meta=METADATA, config=charm_configuration, actions=ACTIONS, unit_id=0
    )
    sock_dns = socket.getfqdn()

    # When
    if SUBSTRATE == "vm":
        with ctx(ctx.on.config_changed(), state_in) as manager:
            charm = cast(KafkaCharm, manager.charm)
            built_sans = charm.broker.tls_manager.build_sans()

        # Then
        assert built_sans == {
            "sans_ip": ["treebeard"],
            "sans_dns": [f"{CHARM_KEY}/0", sock_dns, "worker0.com"],
        }

    elif SUBSTRATE == "k8s":
        # NOTE previous k8s sans_ip like kafka-k8s-0.kafka-k8s-endpoints or binding pod address
        with (
            patch("ops.model.Model.get_binding"),
            patch(
                "core.models.KafkaBroker.node_ip",
                new_callable=PropertyMock,
                return_value="palantir",
            ),
            ctx(ctx.on.config_changed(), state_in) as manager,
        ):
            charm = cast(KafkaCharm, manager.charm)
            built_sans = charm.broker.tls_manager.build_sans()

        # Then
        assert sorted(built_sans["sans_dns"]) == sorted(
            [
                "kafka-k8s-0",
                "kafka-k8s-0.kafka-k8s-endpoints",
                sock_dns,
                "worker0.com",
            ]
        )
        assert "palantir" in "".join(built_sans["sans_ip"])
