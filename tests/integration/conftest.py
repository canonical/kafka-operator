#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest


def pytest_addoption(parser):
    """Defines pytest parsers."""
    parser.addoption(
        "--revision",
        action="store",
        help="Charm rev. to use for tests, will use a locally built .charm file if not provided.",
        default="",
    )


@pytest.fixture(scope="module")
def test_charm_revision(request: pytest.FixtureRequest) -> int | None:
    """Return the charm revision to use for tests."""
    if raw := f'{request.config.getoption("--revision")}':
        return int(raw)

    return None


@pytest.fixture(scope="module")
def test_charm_channel(test_charm_revision: int | None) -> str | None:
    """Return the charm channel to use for tests, if a revision is pinned."""
    if test_charm_revision:
        return "4/edge"

    return None
