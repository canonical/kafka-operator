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
from ops import BoundEvent
from ops.testing import Container, Context, PeerRelation, Secret, State
from tests.unit.helpers import generate_tls_artifacts
from tests.unit.test_secrets import TLS_PK_KEY
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


@pytest.mark.parametrize("broker_pk", ["stale", "fresh", "empty"])
@pytest.mark.parametrize("secret_pk_empty", [True, False])
@pytest.mark.parametrize("pk_kind", ["lib", "secret", ""])
def test_set_tls_private_key(
    ctx: Context,
    base_state: State,
    broker_pk: str,
    secret_pk_empty: bool,
    pk_kind: str,
):
    tls_artifacts = generate_tls_artifacts(
        subject=f"{CHARM_KEY}/0",
        sans_ip=["10.10.10.10"],
        sans_dns=[f"{CHARM_KEY}/0"],
        with_intermediate=False,
    )
    alt_tls_artifacts = generate_tls_artifacts(
        subject=f"{CHARM_KEY}/0",
        sans_ip=["20.20.20.20"],
        sans_dns=[f"{CHARM_KEY}/0"],
        with_intermediate=False,
    )

    secret_content = {f"{CHARM_KEY}-0": tls_artifacts.private_key if not secret_pk_empty else ""}

    cluster_peer = PeerRelation(
        PEER,
        PEER,
        local_unit_data={"private-key-kind": pk_kind},
    )
    tls_private_key_secret = Secret(label="tls_private_key", tracked_content=secret_content)
    state_in = dataclasses.replace(
        base_state,
        relations=[cluster_peer],
        secrets=[tls_private_key_secret],
        config=(
            base_state.config
            | ({TLS_PK_KEY: tls_private_key_secret.id} if not secret_pk_empty else {})
        ),
    )

    match broker_pk:
        case "stale":
            unit_pk = alt_tls_artifacts.private_key
        case "fresh":
            unit_pk = secret_content[f"{CHARM_KEY}-0"] or None
        case _:
            unit_pk = None

    # When
    with (
        ctx(ctx.on.secret_changed(tls_private_key_secret), state_in) as mgr,
        patch(
            "events.tls.TLSHandler.refresh_tls_certificates",
            new_callable=PropertyMock(spec=BoundEvent),
        ) as patched,
        patch(
            "core.models.TLSState.private_key",
            new_callable=PropertyMock(return_value=(unit_pk)),
        ),
    ):
        charm = cast(KafkaCharm, mgr.charm)
        _ = mgr.run()

        # Then
        if not pk_kind and secret_pk_empty and broker_pk == "stale":
            # case cannot happen
            return

        # broker-pk is up-to-date with the secret, nothing should change here
        if broker_pk == "fresh":
            assert not patched.emit.call_count
            assert charm.state.unit_broker.private_key_kind == pk_kind or "lib"

        # secret is empty during/after normal start-up (i.e never provided), nothing should change here
        if secret_pk_empty and pk_kind != "secret":
            assert not patched.emit.call_count
            assert charm.state.unit_broker.private_key_kind != "secret"

        # secret got set, current broker-pk needs updating, we want to see a refresh
        if not secret_pk_empty and pk_kind == "lib" and broker_pk != "fresh":
            assert charm.state.unit_broker.private_key_kind == "secret"
            assert patched.emit.call_count

        # other edge-cases
        if broker_pk == "stale" and pk_kind != "lib":
            if not secret_pk_empty:
                assert charm.state.unit_broker.private_key_kind == "secret"
            else:
                assert charm.state.unit_broker.private_key_kind == "lib"

            assert patched.emit.call_count


@pytest.mark.parametrize(
    ["config_option", "extra_sans", "expected"],
    [
        ("certificate-extra-sans", "", []),
        ("certificate-extra-sans", "worker{unit}.com", ["worker0.com"]),
        (
            "certificate-extra-sans",
            "worker{unit}.com,{unit}.example",
            ["worker0.com", "0.example"],
        ),
        (
            "extra-listeners",
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
    charm_configuration["options"]["certificate-extra-sans"]["default"] = "worker{unit}.com"
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
