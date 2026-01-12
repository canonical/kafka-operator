#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import os
import pathlib
import subprocess
import typing

import jubilant
import pytest

from integration.helpers import APP_NAME, CONTROLLER_NAME, KRaftMode


def pytest_addoption(parser):
    """Defines pytest parsers."""
    parser.addoption(
        "--model",
        action="store",
        help="Juju model to use; if not provided, a new model "
        "will be created for each test which requires one",
    )
    parser.addoption(
        "--keep-models",
        action="store_true",
        help="Keep models handled by opstest, can be overridden in track_model",
    )
    parser.addoption(
        "--kraft-mode", action="store", help="KRaft mode to run the tests", default="single"
    )


def _find_charm(charm_path: typing.Union[str, os.PathLike]) -> pathlib.Path:
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
            f"More than one matching .charm file found at {charm_path=} for {architecture=}."
        )
    else:
        raise FileNotFoundError(f"Unable to find .charm file for {architecture=} at {charm_path=}")


def _build_charm(path: str) -> None:
    if os.environ.get("CI"):
        return

    # try:
    #     _find_charm(path)
    # except FileNotFoundError:
    #     pass

    # Build locally
    cwd = os.getcwd()
    os.chdir(path)
    failed = os.system("charmcraft pack -v")
    os.chdir(cwd)

    if failed:
        raise RuntimeError("Charm build failed")


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
def kafka_charm():
    """Kafka charm used for integration testing."""
    charm_path = "."
    _build_charm(charm_path)
    return _find_charm(charm_path)


@pytest.fixture(scope="module")
def app_charm():
    """Build the application charm."""
    charm_path = "tests/integration/app-charm"
    _build_charm(charm_path)
    return _find_charm(charm_path)


@pytest.fixture(scope="module")
def juju(request: pytest.FixtureRequest):
    model = request.config.getoption("--model")
    keep_models = typing.cast(bool, request.config.getoption("--keep-models"))

    if model is None:
        with jubilant.temp_model(keep=keep_models) as juju:
            juju.wait_timeout = 10 * 60
            juju.model_config({"update-status-hook-interval": "180s"})
            yield juju

            log = juju.debug_log(limit=1000)
    else:
        juju = jubilant.Juju(model=model)
        yield juju
        log = juju.debug_log(limit=1000)

    if request.session.testsfailed:
        print(log, end="")
