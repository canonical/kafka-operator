#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path
from typing import Iterator

import pytest
import yaml
from ops.testing import Harness

from charm import KafkaCharm
from literals import BALANCER_SERVICE, CHARM_KEY, CONTAINER, PEER, SUBSTRATE

pytestmark = pytest.mark.balancer

logger = logging.getLogger(__name__)


CONFIG = str(yaml.safe_load(Path("./config.yaml").read_text()))
ACTIONS = str(yaml.safe_load(Path("./actions.yaml").read_text()))
METADATA = str(yaml.safe_load(Path("./metadata.yaml").read_text()))


@pytest.fixture
def harness_balancer() -> Iterator[Harness[KafkaCharm]]:
    harness = Harness(KafkaCharm, meta=METADATA, actions=ACTIONS, config=CONFIG)

    if SUBSTRATE == "k8s":
        harness.set_can_connect(CONTAINER, True)

    harness._update_config({"role": "balancer"})
    harness.begin()
    yield harness
    harness.cleanup()


@pytest.fixture
def harness_broker() -> Iterator[Harness[KafkaCharm]]:
    harness = Harness(KafkaCharm, meta=METADATA, actions=ACTIONS, config=CONFIG)

    if SUBSTRATE == "k8s":
        harness.set_can_connect(CONTAINER, True)

    harness._update_config({"role": "broker"})
    harness.begin()
    yield harness
    harness.cleanup()


def test_balancer_created_information(harness_balancer):
    with harness_balancer.hooks_disabled():
        harness_balancer.add_relation(PEER, CHARM_KEY)
        harness_balancer.set_leader(True)

    _ = harness_balancer.add_relation(BALANCER_SERVICE, "broker")
    assert harness_balancer.charm.state.balancer.relation_data == {"foo": "bar"}
