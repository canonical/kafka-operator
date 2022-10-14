#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from pathlib import Path
import pytest
from ops.testing import Harness
import yaml
from charm import KafkaCharm

from literals import CHARM_KEY


CONFIG = str(yaml.safe_load(Path("./config.yaml").read_text()))
ACTIONS = str(yaml.safe_load(Path("./actions.yaml").read_text()))
METADATA = str(yaml.safe_load(Path("./metadata.yaml").read_text()))

@pytest.fixture
def harness():
    harness = Harness(KafkaCharm, meta=METADATA)
    harness.add_relation("restart", CHARM_KEY)
    harness._update_config({"offsets-retention-minutes": 10080, "log-retention-hours": 168, "auto-create-topics": False})
    harness.begin()
    return harness
