#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import jubilant
import pytest

from integration.helpers.jubilant import (
    APP_NAME,
    AUTH_SECRET_NAME,
    BASE,
    all_active_idle,
    deploy_cluster,
    get_user,
    set_password,
)
from literals import INTER_BROKER_USER

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker

DUMMY_NAME = "app"
REL_NAME_ADMIN = "kafka-client-admin"


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
def test_build_and_deploy(juju: jubilant.Juju, kraft_mode, kafka_charm, app_charm, kafka_apps):
    deploy_cluster(
        juju=juju,
        charm=kafka_charm,
        kraft_mode=kraft_mode,
        num_broker=3,
    )
    juju.deploy(app_charm, app=DUMMY_NAME, num_units=1, base=BASE)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=2000,
    )

    # needed to open localhost ports
    juju.integrate(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=3600,
    )


def test_password_rotation(juju: jubilant.Juju, kafka_apps):
    """Check that password stored on cluster has changed after a password rotation."""
    initial_replication_user = get_user(
        username=INTER_BROKER_USER,
        model_full_name=juju.model,
    )

    set_password(juju, username=INTER_BROKER_USER, password="newpass123")

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=900,
    )

    new_replication_user = get_user(
        username=INTER_BROKER_USER,
        model_full_name=juju.model,
    )

    assert initial_replication_user != new_replication_user
    assert "newpass123" in new_replication_user

    # Update secret
    juju.update_secret(AUTH_SECRET_NAME, content={"replication": "updatedpass"})

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=900,
    )

    updated_replication_user = get_user(
        username=INTER_BROKER_USER,
        model_full_name=juju.model,
    )

    assert new_replication_user != updated_replication_user
    assert "updatedpass" in updated_replication_user
