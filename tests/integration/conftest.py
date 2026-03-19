#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


import os

import pytest

from .adapters import JujuFixture, temp_model_fixture


@pytest.fixture(scope="module")
def usernames():
    return set()


@pytest.fixture(scope="module")
def kafka_charm(juju: JujuFixture):
    """Kafka charm used for integration testing."""
    charm = juju.ext.build_charm(".", use_cache=bool(os.environ.get("CI", False)))
    return charm


@pytest.fixture(scope="module")
def app_charm(juju: JujuFixture):
    """Build the application charm."""
    charm_path = "tests/integration/app-charm"
    charm = juju.ext.build_charm(charm_path, use_cache=bool(os.environ.get("CI", False)))
    return charm


@pytest.fixture(scope="module")
def juju(request: pytest.FixtureRequest):
    """Pytest fixture that wraps :meth:`jubilant.with_model`.

    This adds command line parameter ``--keep-models`` (see help for details).
    """
    model = request.config.getoption("--model")
    keep_models = bool(request.config.getoption("--keep-models"))

    if model:
        juju = JujuFixture(model=model)
        yield juju
    else:
        with temp_model_fixture(keep=keep_models) as juju:
            yield juju
