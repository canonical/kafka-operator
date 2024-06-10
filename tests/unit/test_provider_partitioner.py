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
from literals import CHARM_KEY, CONTAINER, PARTITIONER_SERVICE, PEER, SUBSTRATE

pytestmark = pytest.mark.partitioner

logger = logging.getLogger(__name__)


CONFIG = str(yaml.safe_load(Path("./config.yaml").read_text()))
ACTIONS = str(yaml.safe_load(Path("./actions.yaml").read_text()))
METADATA = str(yaml.safe_load(Path("./metadata.yaml").read_text()))


@pytest.fixture
def harness_partitioner() -> Iterator[Harness[KafkaCharm]]:
    harness = Harness(KafkaCharm, meta=METADATA, actions=ACTIONS, config=CONFIG)

    if SUBSTRATE == "k8s":
        harness.set_can_connect(CONTAINER, True)

    harness._update_config({"role": "partitioner"})
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


def test_partitioner_created_information(harness_partitioner):
    with harness_partitioner.hooks_disabled():
        harness_partitioner.add_relation(PEER, CHARM_KEY)
        harness_partitioner.set_leader(True)

    _ = harness_partitioner.add_relation(PARTITIONER_SERVICE, "broker")
    assert harness_partitioner.charm.state.partitioner.relation_data == {"foo": "bar"}