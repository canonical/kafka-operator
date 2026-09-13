#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from common.single_kernel_kafka.core.structured_config import ConnectCharmConfig as CharmConfig
from common.single_kernel_kafka.managers.connect_config import DEFAULT_CONFIG_OPTIONS
from ops.testing import Context, PeerRelation, State
from pydantic import ValidationError
from typing_extensions import override

from ..helpers import CLUSTER_DOMAIN, MODEL_NAME
from .helpers import PEER_REL, SUBSTRATE, SUBSTRATE_CLS, ConnectCharm

logger = logging.getLogger(__name__)

CONFIG = yaml.safe_load(Path(f"./connect_{SUBSTRATE_CLS.lower()}/config.yaml").read_text())


@dataclass
class ConfigOverride:
    """Helper dataclass for overriding default charm config value(s) in parametrized tests."""

    key: str
    values: list[Any]
    valid: bool = True

    @override
    def __str__(self):
        state = "VALID" if self.valid else "INVALID"
        return f'{self.key}: {",".join([str(v) for v in self.values])} -> {state}'


def test_defaults(ctx: Context, base_state: State, active_service) -> None:
    """Checks `ConfigManager` populates default config properties properly based on charm config & opinionated, hard-coded defaults."""
    # Given
    state_in = base_state

    # When
    with (ctx(ctx.on.update_status(), state_in) as mgr,):
        charm: ConnectCharm = cast(ConnectCharm, mgr.charm)
        _ = mgr.run()

    # Then
    for line in DEFAULT_CONFIG_OPTIONS.split("\n"):
        assert line.strip() in charm.config_manager.properties

    assert "exactly.once.source.support=disabled" in charm.config_manager.properties
    assert (
        "key.converter=org.apache.kafka.connect.json.JsonConverter"
        in charm.config_manager.properties
    )
    assert (
        "value.converter=org.apache.kafka.connect.json.JsonConverter"
        in charm.config_manager.properties
    )

    # blacklists assertion
    assert "profile=production" not in charm.config_manager.properties
    assert "# profile=production" in charm.config_manager.properties
    assert "rest_port=8083" not in charm.config_manager.properties
    assert "# rest_port=8083" in charm.config_manager.properties
    assert "log_level=LogLevel.INFO" not in charm.config_manager.properties
    assert "# log_level=LogLevel.INFO" in charm.config_manager.properties


@pytest.mark.parametrize(
    "override",
    [
        ConfigOverride(key="exactly_once_source_support", values=[False, True]),
        ConfigOverride(
            key="exactly_once_source_support",
            values=["abc", None, 123, "enabled", "disabled"],
            valid=False,
        ),
        ConfigOverride(key="log_level", values=["DEBUG", "ERROR", "INFO", "WARNING"]),
        ConfigOverride(
            key="log_level", values=["CRITICAL", "test", True, None, 1000], valid=False
        ),
        ConfigOverride(key="profile", values=["testing", "production"]),
        ConfigOverride(key="profile", values=["unknown", "test", None, 123, True], valid=False),
        ConfigOverride(
            key="system_users",
            values=["secret:cvnrnmmupa1s432t4sbg", "secret:cvnrk4uupa1s432t4sag"],
        ),
        ConfigOverride(
            key="system_users",
            values=["cvnrnmmupa1s432t4sbg", "some-text", "my-secret"],
            valid=False,
        ),
    ],
    ids=lambda override: f"{override}",
)
def test_validator(override: ConfigOverride) -> None:
    """Tests `CharmConfig` validator functionality."""
    defaults = {k: v["default"] for k, v in CONFIG["options"].items() if "default" in v}

    for value in override.values:
        target_config = defaults | {override.key: value}

        if not override.valid:
            with pytest.raises(ValidationError):
                config = CharmConfig(**target_config)
        else:
            config = CharmConfig(**target_config)
            assert getattr(config, override.key) == value


def test_empty_string_validator() -> None:
    """Checks empty string will be converted to None and raise a ValidationError."""
    defaults = {k: v["default"] for k, v in CONFIG["options"].items() if "default" in v}

    with pytest.raises(ValidationError):
        _ = CharmConfig(**defaults | {"key_converter": ""})


@pytest.mark.skipif(SUBSTRATE == "vm", reason="Kubernetes DNS resolution only")
def test_rest_endpoints_are_fully_qualified(ctx: Context, base_state: State) -> None:
    """Client-facing REST endpoints must resolve from outside the charm's namespace."""
    # Given
    peer_rel = PeerRelation(PEER_REL, PEER_REL, local_unit_data={"cluster-domain": CLUSTER_DOMAIN})
    state_in = dataclasses.replace(base_state, relations=[peer_rel])

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(ConnectCharm, manager.charm)

        # Then
        assert charm.context.rest_endpoints == (
            f"http://kafka-connect-k8s-0.kafka-connect-k8s-endpoints."
            f"{MODEL_NAME}.svc.{CLUSTER_DOMAIN}:8083"
        ), "the cached cluster domain is used, rather than being resolved on every hook"
        assert (
            charm.context.worker_unit.internal_address
            == "kafka-connect-k8s-0.kafka-connect-k8s-endpoints"
        ), "inter-worker REST traffic never leaves the namespace, so it keeps the short name"
