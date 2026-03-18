#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from time import sleep

import pytest

from .adapters import JujuFixture, gather
from .helpers import APP_NAME, ZK_NAME, get_user, set_password

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker

DUMMY_NAME = "app"
REL_NAME_ADMIN = "kafka-client-admin"


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
def test_build_and_deploy(juju: JujuFixture, kafka_charm, app_charm):
    gather(
        juju.ext.model.deploy(
            ZK_NAME, channel="edge", application_name=ZK_NAME, num_units=1, series="jammy"
        ),
        juju.ext.model.deploy(kafka_charm, application_name=APP_NAME, num_units=1, series="jammy"),
        juju.ext.model.deploy(app_charm, application_name=DUMMY_NAME, num_units=1, series="jammy"),
    )
    juju.ext.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME], timeout=2000, idle_period=30, raise_on_error=False
    )

    # needed to open localhost ports
    juju.ext.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    juju.ext.model.add_relation(APP_NAME, ZK_NAME)

    with juju.ext.fast_forward(fast_interval="30s"):
        sleep(90)

    juju.ext.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME, DUMMY_NAME], status="active", idle_period=30, timeout=3600
    )


def test_password_rotation(juju: JujuFixture):
    """Check that password stored on ZK has changed after a password rotation."""
    initial_sync_user = get_user(
        username="sync",
        model_full_name=juju.ext.model_full_name,
    )

    result = set_password(juju, username="sync", num_unit=0)
    assert "sync-password" in result.keys()

    juju.ext.model.wait_for_idle(apps=[APP_NAME, ZK_NAME], status="active", idle_period=30)

    new_sync_user = get_user(
        username="sync",
        model_full_name=juju.ext.model_full_name,
    )

    assert initial_sync_user != new_sync_user
