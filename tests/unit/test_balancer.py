#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import patch

import pytest

from managers.balancer import CruiseControlClient


@pytest.fixture
def client():
    return CruiseControlClient("Beren", "Luthien")


def test_client_get_args(client):
    with patch("managers.balancer.requests.get") as patched_get:
        client.get("silmaril")

        _, kwargs = patched_get.call_args

        assert kwargs["params"]["json"]
        assert kwargs["params"]["json"] == "True"

        assert kwargs["auth"]
        assert kwargs["auth"] == ("Beren", "Luthien")


def test_client_post_args(client):
    with patch("managers.balancer.requests.post") as patched_post:
        client.post("silmaril")

        _, kwargs = patched_post.call_args

        assert kwargs["params"]["json"]
        assert kwargs["params"]["dryrun"]
        assert kwargs["auth"]

        assert kwargs["params"]["json"] == "True"
        assert kwargs["params"]["dryrun"] == "False"
        assert kwargs["auth"] == ("Beren", "Luthien")
