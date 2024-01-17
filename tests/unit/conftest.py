#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from literals import INTERNAL_USERS


@pytest.fixture(scope="module")
def zk_data() -> dict[str, str]:
    return {
        "username": "glorfindel",
        "password": "mellon",
        "endpoints": "10.10.10.10",
        "chroot": "/kafka",
        "uris": "10.10.10.10:2181",
        "tls": "disabled",
    }


@pytest.fixture(scope="module")
def passwords_data() -> dict[str, str]:
    return {f"{user}-password": "mellon" for user in INTERNAL_USERS}
