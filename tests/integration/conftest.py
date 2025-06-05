#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from pytest_operator.plugin import OpsTest

from .helpers import APP_NAME, CONTROLLER_NAME, KRaftMode


def pytest_addoption(parser):
    """Defines pytest parsers."""
    parser.addoption(
        "--kraft-mode", action="store", help="KRaft mode to run the tests", default="single"
    )


@pytest.fixture(scope="module")
def kraft_mode(request: pytest.FixtureRequest) -> KRaftMode:
    """Returns the KRaft mode which is used to run the tests, should be either `single` or `multi`."""
    mode = f'{request.config.getoption("--kraft-mode")}' or "single"
    if mode not in ("single", "multi"):
        raise Exception("Unknown --kraft-mode, valid options are 'single' and 'multi'")

    return mode


@pytest.fixture(scope="module")
def controller_app(kraft_mode) -> str:
    """Returns the name of the controller application."""
    return APP_NAME if kraft_mode == "single" else CONTROLLER_NAME


@pytest.fixture(scope="module")
def kafka_apps(kraft_mode) -> list[str]:
    """Returns a list of applications used to deploy the Apache Kafka cluster, depending on KRaft mode.

    This would be either [broker_app] for single mode,  or [broker_app, controller_app] for multi mode.
    This fixture is useful for wait calls for example.
    """
    return [APP_NAME] if kraft_mode == "single" else [APP_NAME, CONTROLLER_NAME]


@pytest.fixture(scope="module")
def usernames():
    return set()


@pytest.fixture(scope="module")
async def kafka_charm(ops_test: OpsTest):
    """Kafka charm used for integration testing."""
    charm = await ops_test.build_charm(".")
    return charm


@pytest.fixture(scope="module")
async def app_charm(ops_test: OpsTest):
    """Build the application charm."""
    charm_path = "tests/integration/app-charm"
    charm = await ops_test.build_charm(charm_path)
    return charm
