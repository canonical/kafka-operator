#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import os
import pathlib
import subprocess
import typing

import pytest
from pytest_operator.plugin import OpsTest

from .helpers import APP_NAME, CONTROLLER_NAME, KRaftMode


def pytest_addoption(parser):
    """Defines pytest parsers."""
    parser.addoption(
        "--kraft-mode", action="store", help="KRaft mode to run the tests", default="single"
    )


# TODO: this a temp solution until we migrate to DP workflows for int. testing
def pytest_configure(config):
    if os.environ.get("CI") == "true":
        # Running in GitHub Actions; skip build step
        plugin = config.pluginmanager.get_plugin("pytest-operator")
        plugin.OpsTest.build_charm = _build_charm

        # Remove charmcraft dependency from `ops_test` fixture
        check_deps = plugin.check_deps
        plugin.check_deps = lambda *deps: check_deps(*(dep for dep in deps if dep != "charmcraft"))


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


async def _build_charm(self, charm_path: typing.Union[str, os.PathLike]) -> pathlib.Path:
    charm_path = pathlib.Path(charm_path)
    architecture = subprocess.run(
        ["dpkg", "--print-architecture"],
        capture_output=True,
        check=True,
        encoding="utf-8",
    ).stdout.strip()
    assert architecture in ("amd64", "arm64")
    packed_charms = list(charm_path.glob(f"*{architecture}.charm"))
    if len(packed_charms) == 1:
        # python-libjuju's model.deploy(), juju deploy, and juju bundle files expect local charms
        # to begin with `./` or `/` to distinguish them from Charmhub charms.
        # Therefore, we need to return an absolute path—a relative `pathlib.Path` does not start
        # with `./` when cast to a str.
        # (python-libjuju model.deploy() expects a str but will cast any input to a str as a
        # workaround for pytest-operator's non-compliant `build_charm` return type of
        # `pathlib.Path`.)
        return packed_charms[0].resolve(strict=True)
    elif len(packed_charms) > 1:
        raise ValueError(
            f"More than one matching .charm file found at {charm_path=} for {architecture=} and "
            f"Ubuntu 22.04: {packed_charms}."
        )
    else:
        raise ValueError(
            f"Unable to find .charm file for {architecture=} and Ubuntu 22.04 at {charm_path=}"
        )
