#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import os
from pathlib import Path

import pytest
from pytest_operator.plugin import OpsTest


@pytest.fixture(scope="module")
def usernames():
    return set()


@pytest.fixture(scope="module")
async def kafka_charm(ops_test: OpsTest):
    """Kafka charm used for integration testing."""
    in_ci = os.environ.get("CI", None) is not None
    local_charm = next(iter(Path(".").glob("*.charm")), None)
    if in_ci and local_charm is not None:
        return local_charm.absolute()

    charm = await ops_test.build_charm(".")
    return charm


@pytest.fixture(scope="module")
async def app_charm(ops_test: OpsTest):
    """Build the application charm."""
    charm_path = "tests/integration/app-charm"
    charm = await ops_test.build_charm(charm_path)
    return charm
