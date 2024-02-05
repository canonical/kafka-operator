#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from pathlib import Path

import pytest
from pytest_operator.plugin import OpsTest


@pytest.fixture(scope="module")
def usernames():
    return set()


@pytest.fixture(scope="module")
async def kafka_charm(ops_test: OpsTest) -> Path:
    """Kafka charm used for integration testing."""
    charm = await ops_test.build_charm(".")
    return charm


@pytest.fixture(scope="module")
async def app_charm(ops_test: OpsTest) -> Path:
    """Build the application charm."""
    charm_path = "tests/integration/app-charm"
    charm = await ops_test.build_charm(charm_path)
    return charm
