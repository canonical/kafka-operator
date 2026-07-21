#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import jubilant
from single_kernel_kafka.core.literals import INTER_BROKER_USER
from tenacity import (
    RetryError,
    Retrying,
    stop_after_attempt,
    wait_fixed,
)

from integration.k8s.helpers.jubilant import all_active_idle, deploy_cluster
from integration.k8s.helpers.legacy import (
    AUTH_SECRET_NAME,
    get_user,
    set_password,
)

logger = logging.getLogger(__name__)


def _assert_password_updated(model_full_name: str, old_user: str, expected_password: str):
    try:
        for attempt in Retrying(stop=stop_after_attempt(5), wait=wait_fixed(30)):
            with attempt:
                new_user = get_user(
                    username=INTER_BROKER_USER,
                    model_full_name=model_full_name,
                )
                assert old_user != new_user
                assert expected_password in new_user
                return
    except RetryError:
        assert False, "Password update assertion failed after 5 attempts."


def test_build_and_deploy(juju: jubilant.Juju, kafka_charm, kraft_mode):
    deploy_cluster(
        juju=juju,
        charm=kafka_charm,
        kraft_mode=kraft_mode,
        config_broker={"expose-external": "nodeport"},
        num_broker=3,
        num_controller=3,
    )


def test_password_rotation(juju: jubilant.Juju, kafka_apps):
    """Check that password stored on cluster has changed after a password rotation."""
    assert juju.model
    initial_replication_user = get_user(
        username=INTER_BROKER_USER,
        model_full_name=juju.model,
    )

    set_password(juju, username=INTER_BROKER_USER, password="newpass123")

    juju.wait(lambda status: all_active_idle(status, *kafka_apps), delay=3, successes=10)

    _assert_password_updated(
        juju.model, old_user=initial_replication_user, expected_password="newpass123"
    )

    new_replication_user = get_user(
        username=INTER_BROKER_USER,
        model_full_name=juju.model,
    )

    # Update secret
    juju.update_secret(
        AUTH_SECRET_NAME,
        content={INTER_BROKER_USER: "updatedpass"},
    )

    juju.wait(lambda status: all_active_idle(status, *kafka_apps), delay=3, successes=10)

    _assert_password_updated(
        juju.model, old_user=new_replication_user, expected_password="updatedpass"
    )
