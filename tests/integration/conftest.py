# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from pytest_operator.plugin import OpsTest


@pytest.fixture(scope="module")
def usernames():
    return set()


@pytest.fixture(scope="module")
async def app_charm(ops_test: OpsTest):
    """Build the application charm."""
    charm_path = "tests/integration/app-charm"
    charm = await ops_test.build_charm(charm_path)
    return charm
