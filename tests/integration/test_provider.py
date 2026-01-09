#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time

import jubilant
import pytest

from integration.helpers.jubilant import (
    BASE,
    all_active_idle,
    check_user,
    deploy_cluster,
    get_client_usernames,
    get_provider_data,
    load_acls,
    load_super_users,
)
from literals import CONTROLLER_USER, INTERNAL_USERS

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker

APP_NAME = "kafka"
DUMMY_NAME_1 = "app"
DUMMY_NAME_2 = "appii"
DUMMY_NAME_3 = "prefix-app"
TLS_NAME = "self-signed-certificates"

REL_NAME_CONSUMER = "kafka-client-consumer"
REL_NAME_PRODUCER = "kafka-client-producer"
REL_NAME_ADMIN = "kafka-client-admin"
REL_NAME_CERTIFICATES = "certificates"

NON_REL_USERS = set(INTERNAL_USERS + [CONTROLLER_USER])


def test_deploy_charms_relate_active(
    juju: jubilant.Juju, kraft_mode, kafka_charm, app_charm, kafka_apps, usernames: set[str]
):
    """Test deploy and relate operations."""
    deploy_cluster(
        juju=juju,
        charm=kafka_charm,
        kraft_mode=kraft_mode,
    )
    juju.deploy(app_charm, app=DUMMY_NAME_1, num_units=1, base=BASE)
    juju.cli("model-config", "update-status-hook-interval=60s")

    juju.integrate(APP_NAME, f"{DUMMY_NAME_1}:{REL_NAME_CONSUMER}")

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME_1),
        delay=3,
        successes=10,
        timeout=2000,
    )

    usernames.update(get_client_usernames(juju))

    for username in set(usernames) - NON_REL_USERS:
        check_user(
            username=username,
            model_full_name=juju.model,
        )

    for acl in load_acls(model_full_name=juju.model):
        assert acl.username in usernames
        assert acl.operation in ["READ", "DESCRIBE"]
        assert acl.resource_type in ["GROUP", "TOPIC"]
        if acl.resource_type == "TOPIC":
            assert acl.resource_name == "test-topic"
        if acl.resource_type == "GROUP":
            assert acl.resource_name == "test-prefix"


def test_deploy_multiple_charms_same_topic_relate_active(
    juju: jubilant.Juju, app_charm, kafka_apps, usernames: set[str]
):
    """Test relation with multiple applications."""
    juju.deploy(app_charm, app=DUMMY_NAME_2, num_units=1)
    juju.integrate(APP_NAME, f"{DUMMY_NAME_2}:{REL_NAME_CONSUMER}")

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME_2),
        delay=3,
        successes=20,
        timeout=900,
    )

    usernames.update(get_client_usernames(juju))
    for username in set(usernames) - NON_REL_USERS:
        check_user(
            username=username,
            model_full_name=juju.model,
        )

    for acl in load_acls(model_full_name=juju.model):
        assert acl.username in usernames
        assert acl.operation in ["READ", "DESCRIBE"]
        assert acl.resource_type in ["GROUP", "TOPIC"]
        if acl.resource_type == "TOPIC":
            assert acl.resource_name == "test-topic"


def test_remove_application_removes_user_and_acls(
    juju: jubilant.Juju, kafka_apps, usernames: set[str]
):
    """Test the correct removal of user and permission after relation removal."""
    juju.remove_application(DUMMY_NAME_1)
    time.sleep(60)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME_2),
        delay=3,
        successes=20,
        timeout=900,
    )

    # checks that old users are removed from active cluster ACLs
    acls = load_acls(model_full_name=juju.model)
    acl_usernames = set()
    for acl in acls:
        acl_usernames.add(acl.username)

    assert acl_usernames != usernames

    # checks that past usernames no longer exist
    with pytest.raises(AssertionError):
        for username in usernames:
            check_user(
                username=username,
                model_full_name=juju.model,
            )


def test_deploy_producer_same_topic(
    juju: jubilant.Juju, app_charm, kafka_apps, usernames: set[str]
):
    """Test the correct deployment and relation with role producer."""
    juju.deploy(app_charm, app=DUMMY_NAME_1, num_units=1, base=BASE)
    juju.integrate(APP_NAME, f"{DUMMY_NAME_1}:{REL_NAME_PRODUCER}")

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME_1),
        delay=3,
        successes=20,
        timeout=900,
    )

    acls = load_acls(model_full_name=juju.model)
    acl_usernames = set()
    for acl in acls:
        acl_usernames.add(acl.username)

    usernames.update(get_client_usernames(juju))

    for acl in acls:
        assert acl.username in usernames
        assert acl.operation in ["READ", "DESCRIBE", "CREATE", "WRITE"]
        assert acl.resource_type in ["GROUP", "TOPIC"]
        if acl.resource_type == "TOPIC":
            assert acl.resource_name == "test-topic"

    # remove application
    juju.remove_application(DUMMY_NAME_1)
    time.sleep(60)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=3,
        successes=10,
        timeout=900,
    )


def test_admin_added_to_super_users(juju: jubilant.Juju, app_charm, kafka_apps):
    """Test relation with admin privileges."""
    super_users = load_super_users(model_full_name=juju.model)
    assert len(super_users) == 3  # controller, replication, operator

    juju.deploy(app_charm, app=DUMMY_NAME_1, num_units=1, base=BASE)
    juju.integrate(APP_NAME, f"{DUMMY_NAME_1}:{REL_NAME_ADMIN}")

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME_1),
        delay=3,
        successes=20,
        timeout=900,
    )

    # check the correct addition of super-users
    super_users = load_super_users(model_full_name=juju.model)
    assert len(super_users) == 4


def test_admin_removed_from_super_users(juju: jubilant.Juju, kafka_apps):
    """Test that removal of the relation with admin privileges."""
    juju.remove_application(DUMMY_NAME_1)
    time.sleep(60)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME_2),
        delay=3,
        successes=20,
        timeout=900,
    )

    super_users = load_super_users(model_full_name=juju.model)
    assert len(super_users) == 3

    # adding cleanup to save memory
    juju.remove_application(DUMMY_NAME_2)
    time.sleep(30)


def test_prefixed_topic_creation(juju: jubilant.Juju, app_charm, kafka_apps):
    juju.deploy(
        app_charm,
        app=DUMMY_NAME_3,
        num_units=1,
        base=BASE,
        config={"topic-name": "test-*"},
    )
    juju.integrate(APP_NAME, f"{DUMMY_NAME_3}:{REL_NAME_PRODUCER}")

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME_3),
        delay=3,
        successes=20,
        timeout=1800,
    )

    response = juju.run(f"{DUMMY_NAME_3}/0", "create-topic")
    assert response.results.get("success", None) == "TRUE"


def test_connection_updated_on_tls_enabled(juju: jubilant.Juju, app_charm, kafka_apps):
    """Test relation when TLS is enabled."""
    # adding new app unit to validate
    juju.deploy(app_charm, app=DUMMY_NAME_1, num_units=1)
    juju.integrate(APP_NAME, f"{DUMMY_NAME_1}:{REL_NAME_CONSUMER}")

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME_1),
        delay=3,
        successes=20,
        timeout=1200,
    )

    # deploying tls
    tls_config = {"ca-common-name": "kafka"}
    juju.deploy(TLS_NAME, channel="1/stable", config=tls_config)

    juju.wait(
        lambda status: all_active_idle(status, TLS_NAME),
        delay=3,
        successes=10,
        timeout=900,
    )

    # relating tls with kafka
    juju.integrate(TLS_NAME, f"{APP_NAME}:{REL_NAME_CERTIFICATES}")
    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME_1, TLS_NAME),
        delay=3,
        successes=20,
        timeout=1800,
    )

    # ensure at least one update-status run
    time.sleep(120)

    # Check that related application has updated information
    provider_data = get_provider_data(
        model=juju.model,
        unit_name=next(iter(juju.status().apps[DUMMY_NAME_1].units)),
        relation_interface="kafka-client-consumer",
        owner=APP_NAME,
    )

    assert provider_data["tls"] == "enabled"
    assert "9093" in provider_data["endpoints"]
    assert "test-prefix" in provider_data["consumer-group-prefix"]
    assert "test-topic" in provider_data["topic"]
