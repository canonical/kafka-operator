#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from ops.testing import Harness

from charm import KafkaCharm
from literals import (
    CONTAINER,
    SUBSTRATE,
)

pytestmark = pytest.mark.partitioner

logger = logging.getLogger(__name__)


CONFIG = str(yaml.safe_load(Path("./config.yaml").read_text()))
ACTIONS = str(yaml.safe_load(Path("./actions.yaml").read_text()))
METADATA = str(yaml.safe_load(Path("./metadata.yaml").read_text()))


@pytest.fixture
def harness() -> Harness:
    harness = Harness(KafkaCharm, meta=METADATA, actions=ACTIONS, config=CONFIG)

    if SUBSTRATE == "k8s":
        harness.set_can_connect(CONTAINER, True)

    harness._update_config({"role": "partitioner"})
    harness.begin()
    return harness


def test_ok(harness):
    pass
