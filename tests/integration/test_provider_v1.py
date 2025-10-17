#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging

import jubilant
import pytest

from integration.helpers.jubilant import (
    BASE,
    all_active_idle,
    deploy_cluster,
    get_provider_data,
    get_secret_by_label,
)
from integration.helpers.pytest_operator import check_user, load_acls
from literals import REL_NAME
from managers.auth import Acl

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker

APP_NAME = "kafka"
DUMMY_NAME_1 = "app"
REL_NAME_V1 = "kafka-client-v1"


USERNAMES = []
PASSWORDS = []


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
def test_deploy_and_relate(
    juju: jubilant.Juju, kafka_charm, app_charm, kraft_mode, kafka_apps
) -> None:
    """Deploys a cluster of Kafka with 3 brokers and a test app, waits for `active|idle`."""
    deploy_cluster(
        juju=juju,
        charm=kafka_charm,
        kraft_mode=kraft_mode,
    )
    juju.deploy(
        app_charm,
        app=DUMMY_NAME_1,
        num_units=1,
        base=BASE,
    )

    juju.integrate(APP_NAME, f"{DUMMY_NAME_1}:{REL_NAME_V1}")

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME_1),
        delay=3,
        successes=20,
        timeout=900,
    )


def test_relation_data_integrity(juju: jubilant.Juju):
    """Check that relation data for a client app with multiple requests is properly set.

    In this scenario, the charm should create two different usernames with different secrets and credentials.
    """
    provider_data = get_provider_data(
        model=juju.model,
        owner=DUMMY_NAME_1,
        unit_name=f"{DUMMY_NAME_1}/0",
        relation_interface=REL_NAME_V1,
    )

    data_requests = json.loads(provider_data.get("requests", "[]"))

    assert len(data_requests) == 2
    for i in range(2):
        for k in ("secret-user", "secret-tls"):
            assert data_requests[0].get(k)

    # Each secret should have its own secret
    assert data_requests[0].get("secret-user") != data_requests[1].get("secret-user")
    assert data_requests[0].get("secret-tls") != data_requests[1].get("secret-tls")

    for i in range(2):
        label = f'{REL_NAME}.{provider_data["relation-id"]}.{data_requests[i].get("request-id")}.user.secret'
        user_secret = get_secret_by_label(
            juju,
            label=label,
            owner=APP_NAME,
        )
        USERNAMES.append(user_secret["username"])
        PASSWORDS.append(user_secret["password"])

    assert USERNAMES[0] != USERNAMES[1]
    assert PASSWORDS[0] != PASSWORDS[1]


def test_acl_integrity(juju: jubilant.Juju):
    """Check that ACLs for a client app with multiple requests is properly set.

    In this scenario, one username have a producer role on the topic named "other",
    and another username should have READ permissions on the mentioned topic.
    """
    provider_data = get_provider_data(
        model=juju.model,
        owner=DUMMY_NAME_1,
        unit_name=f"{DUMMY_NAME_1}/0",
        relation_interface=REL_NAME_V1,
    )
    request_map = json.loads(provider_data.get("data"))

    # We can't rely on the order of requests, so first find the request
    # which had entity permissions attached.
    request_with_entity_permissions = None
    for req, content in request_map.items():
        if content.get("entity-permissions"):
            request_with_entity_permissions = req

    user_with_permissions = next(
        iter(u for u in USERNAMES if request_with_entity_permissions in u)
    )
    user_with_producer_role = next(iter(u for u in USERNAMES if u != user_with_permissions))

    acls = load_acls(model_full_name=juju.model)

    # Assert that the user with producer role has correct permissions
    assert (
        Acl(
            username=user_with_producer_role,
            resource_type="TOPIC",
            resource_name="other",
            operation="WRITE",
        )
        in acls
    )

    # Assert that additional READ permission was assigned to the user_with_permissions
    assert (
        Acl(
            username=user_with_permissions,
            resource_type="TOPIC",
            resource_name="other",
            operation="READ",
        )
        in acls
    )


def test_relation_broken(juju: jubilant.Juju, kafka_apps):
    for username in USERNAMES:
        check_user(juju.model, username)

    juju.remove_relation(APP_NAME, DUMMY_NAME_1)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME_1),
        delay=3,
        successes=20,
        timeout=900,
    )

    for username in USERNAMES:
        with pytest.raises(AssertionError):
            check_user(juju.model, username)
