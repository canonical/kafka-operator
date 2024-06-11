#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from scenario import Context, Relation, State

from charm import KafkaCharm
from literals import BALANCER, BALANCER_SERVICE, BROKER, Status

pytestmark = pytest.mark.balancer

logger = logging.getLogger(__name__)


CONFIG = yaml.safe_load(Path("./config.yaml").read_text())
ACTIONS = yaml.safe_load(Path("./actions.yaml").read_text())
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())


@pytest.fixture()
def charm_configuration():
    """Enable direct mutation on configuration dict."""
    return json.loads(json.dumps(CONFIG))


def test_install_blocks_snap_install_failure(charm_configuration):
    # Given
    charm_configuration["options"]["role"]["default"] = "balancer"
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    state_in = State()

    # When
    with patch("workload.Workload.install", return_value=False):
        state_out = ctx.run("install", state_in)

    # Then
    assert state_out.unit_status == Status.SNAP_NOT_INSTALLED.value.status


def test_ready_to_start_not_implemented(charm_configuration):
    # Given
    charm_configuration["options"]["role"]["default"] = "balancer"
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    state_in = State()

    # When
    with patch("workload.Workload.write"), patch("workload.BalancerWorkload.start"):
        state_out = ctx.run("start", state_in)

    # Then
    assert state_out.unit_status == Status.NOT_IMPLEMENTED.value.status


def test_secrets_requested_by_balancer_on_relation_creation(charm_configuration):
    # Given
    charm_configuration["options"]["role"]["default"] = "balancer"
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    relation = Relation(
        interface=BALANCER.value,
        endpoint=BALANCER_SERVICE,
        remote_app_name=BROKER.value,
    )
    state_in = State(leader=True, relations=[relation])

    # When
    state_out = ctx.run(relation.created_event, state_in)

    # Then
    assert (
        json.loads(state_out.relations[0].local_app_data["requested-secrets"])
        == BALANCER.requested_secrets
    )
