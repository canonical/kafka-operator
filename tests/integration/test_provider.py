#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from time import sleep

import pytest
from jubilant_adapters import JujuFixture, gather

from .helpers import (
    check_user,
    get_client_usernames,
    get_kafka_zk_relation_data,
    get_provider_data,
    load_acls,
    load_super_users,
)

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker

APP_NAME = "kafka"
ZK = "zookeeper"
DUMMY_NAME_1 = "app"
DUMMY_NAME_2 = "appii"
DUMMY_NAME_3 = "prefix-app"
TLS_NAME = "self-signed-certificates"

REL_NAME_CONSUMER = "kafka-client-consumer"
REL_NAME_PRODUCER = "kafka-client-producer"
REL_NAME_ADMIN = "kafka-client-admin"
REL_NAME_CERTIFICATES = "certificates"


def test_deploy_charms_relate_active(
    juju: JujuFixture, kafka_charm, app_charm, usernames: set[str]
):
    """Test deploy and relate operations."""
    gather(
        juju.ext.model.deploy(
            "zookeeper", channel="edge", application_name=ZK, num_units=3, series="jammy"
        ),
        juju.ext.model.deploy(kafka_charm, application_name=APP_NAME, num_units=1, series="jammy"),
        juju.ext.model.deploy(
            app_charm, application_name=DUMMY_NAME_1, num_units=1, series="jammy"
        ),
    )

    juju.ext.model.add_relation(APP_NAME, ZK)
    juju.ext.model.add_relation(APP_NAME, f"{DUMMY_NAME_1}:{REL_NAME_CONSUMER}")

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, ZK, DUMMY_NAME_1],
            idle_period=30,
            status="active",
            timeout=2000,
            raise_on_error=False,
        )

    usernames.update(get_client_usernames(juju))

    for username in usernames:
        check_user(
            username=username,
            model_full_name=juju.ext.model_full_name,
        )

    zk_data = get_kafka_zk_relation_data(juju=juju, owner=ZK, unit_name=f"{APP_NAME}/0")
    zk_uris = zk_data.get("uris", "").split("/")[0]

    for acl in load_acls(model_full_name=juju.ext.model_full_name, zk_uris=zk_uris):
        assert acl.username in usernames
        assert acl.operation in ["READ", "DESCRIBE"]
        assert acl.resource_type in ["GROUP", "TOPIC"]
        if acl.resource_type == "TOPIC":
            assert acl.resource_name == "test-topic"
        if acl.resource_type == "GROUP":
            assert acl.resource_name == "test-prefix"


def test_deploy_multiple_charms_same_topic_relate_active(
    juju: JujuFixture, app_charm, usernames: set[str]
):
    """Test relation with multiple applications."""
    juju.ext.model.deploy(app_charm, application_name=DUMMY_NAME_2, num_units=1)
    juju.ext.model.add_relation(APP_NAME, f"{DUMMY_NAME_2}:{REL_NAME_CONSUMER}")

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, DUMMY_NAME_1, ZK], idle_period=30, status="active"
        )

    usernames.update(get_client_usernames(juju))
    for username in usernames:
        check_user(
            username=username,
            model_full_name=juju.ext.model_full_name,
        )

    zk_data = get_kafka_zk_relation_data(juju=juju, owner=ZK, unit_name=f"{APP_NAME}/0")
    zk_uris = zk_data.get("uris", "").split("/")[0]

    for acl in load_acls(model_full_name=juju.ext.model_full_name, zk_uris=zk_uris):
        assert acl.username in usernames
        assert acl.operation in ["READ", "DESCRIBE"]
        assert acl.resource_type in ["GROUP", "TOPIC"]
        if acl.resource_type == "TOPIC":
            assert acl.resource_name == "test-topic"


def test_remove_application_removes_user_and_acls(juju: JujuFixture, usernames: set[str]):
    """Test the correct removal of user and permission after relation removal."""
    juju.ext.model.remove_application(DUMMY_NAME_1, block_until_done=True)

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(apps=[APP_NAME, ZK], idle_period=30, status="active")

    # checks that old users are removed from active cluster ACLs
    zk_data = get_kafka_zk_relation_data(juju=juju, owner=ZK, unit_name=f"{APP_NAME}/0")
    zk_uris = zk_data.get("uris", "").split("/")[0]

    acls = load_acls(model_full_name=juju.ext.model_full_name, zk_uris=zk_uris)
    acl_usernames = set()
    for acl in acls:
        acl_usernames.add(acl.username)

    assert acl_usernames != usernames

    # checks that past usernames no longer exist
    with pytest.raises(AssertionError):
        for username in usernames:
            check_user(
                username=username,
                model_full_name=juju.ext.model_full_name,
            )


def test_deploy_producer_same_topic(juju: JujuFixture, app_charm, usernames: set[str]):
    """Test the correct deployment and relation with role producer."""
    gather(
        juju.ext.model.deploy(
            app_charm, application_name=DUMMY_NAME_1, num_units=1, series="jammy"
        )
    )
    juju.ext.model.add_relation(APP_NAME, f"{DUMMY_NAME_1}:{REL_NAME_PRODUCER}")

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, DUMMY_NAME_1, ZK], idle_period=30, status="active"
        )

    zk_data = get_kafka_zk_relation_data(juju=juju, owner=ZK, unit_name=f"{APP_NAME}/0")
    zk_uris = zk_data.get("uris", "").split("/")[0]

    acls = load_acls(model_full_name=juju.ext.model_full_name, zk_uris=zk_uris)
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
    juju.ext.model.remove_application(DUMMY_NAME_1, block_until_done=True)
    juju.ext.model.wait_for_idle(apps=[APP_NAME], idle_period=30, status="active")


def test_admin_added_to_super_users(juju: JujuFixture):
    """Test relation with admin privileges."""
    super_users = load_super_users(model_full_name=juju.ext.model_full_name)
    assert len(super_users) == 2

    app_charm = juju.ext.build_charm("tests/integration/app-charm")

    gather(
        juju.ext.model.deploy(
            app_charm, application_name=DUMMY_NAME_1, num_units=1, series="jammy"
        )
    )
    juju.ext.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME_1, ZK])
    juju.ext.model.add_relation(APP_NAME, f"{DUMMY_NAME_1}:{REL_NAME_ADMIN}")
    juju.ext.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME_1])

    assert juju.ext.model.applications[APP_NAME].status == "active"
    assert juju.ext.model.applications[DUMMY_NAME_1].status == "active"

    # check the correct addition of super-users
    super_users = load_super_users(model_full_name=juju.ext.model_full_name)
    assert len(super_users) == 3


def test_admin_removed_from_super_users(juju: JujuFixture):
    """Test that removal of the relation with admin privileges."""
    juju.ext.model.remove_application(DUMMY_NAME_1, block_until_done=True)
    juju.ext.model.wait_for_idle(apps=[APP_NAME])
    assert juju.ext.model.applications[APP_NAME].status == "active"

    juju.ext.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME_2])
    assert juju.ext.model.applications[APP_NAME].status == "active"

    super_users = load_super_users(model_full_name=juju.ext.model_full_name)
    assert len(super_users) == 2

    # adding cleanup to save memory
    juju.ext.model.remove_application(DUMMY_NAME_2, block_until_done=True)


def test_prefixed_topic_creation(juju: JujuFixture, app_charm):
    gather(
        juju.ext.model.deploy(
            app_charm,
            application_name=DUMMY_NAME_3,
            num_units=1,
            series="jammy",
            config={"topic-name": "test-*"},
        )
    )
    juju.ext.model.add_relation(APP_NAME, f"{DUMMY_NAME_3}:{REL_NAME_PRODUCER}")

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, DUMMY_NAME_3, ZK], idle_period=30, status="active"
        )

    action = juju.ext.model.units.get(f"{DUMMY_NAME_3}/0").run_action("create-topic")
    response = action.wait()

    assert response.results.get("success", None) == "TRUE"


def test_connection_updated_on_tls_enabled(juju: JujuFixture, app_charm):
    """Test relation when TLS is enabled."""
    # adding new app unit to validate
    juju.ext.model.deploy(app_charm, application_name=DUMMY_NAME_1, num_units=1)
    juju.ext.model.wait_for_idle(apps=[DUMMY_NAME_1])
    juju.ext.model.add_relation(APP_NAME, f"{DUMMY_NAME_1}:{REL_NAME_CONSUMER}")
    juju.ext.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME_1])

    # deploying tls
    tls_config = {"ca-common-name": "kafka"}
    # FIXME (certs): Unpin the revision once the charm is fixed
    juju.ext.model.deploy(
        TLS_NAME, channel="edge", config=tls_config, series="jammy", revision=163
    )
    juju.ext.model.wait_for_idle(apps=[TLS_NAME], idle_period=30, timeout=1800, status="active")

    # relating tls with zookeeper
    juju.ext.model.add_relation(TLS_NAME, ZK)
    juju.ext.model.wait_for_idle(
        apps=[ZK, TLS_NAME], idle_period=60, timeout=1800, status="active"
    )

    # relating tls with kafka
    juju.ext.model.add_relation(TLS_NAME, f"{APP_NAME}:{REL_NAME_CERTIFICATES}")
    juju.ext.model.wait_for_idle(
        apps=[APP_NAME, ZK, TLS_NAME, DUMMY_NAME_1], timeout=1800, idle_period=60, status="active"
    )

    # ensure at least one update-status run
    with juju.ext.fast_forward(fast_interval="30s"):
        sleep(60)

    # Check that related application has updated information
    provider_data = get_provider_data(
        juju=juju,
        unit_name=f"{DUMMY_NAME_1}/3",
        relation_interface="kafka-client-consumer",
        owner=APP_NAME,
    )

    assert provider_data["tls"] == "enabled"
    assert "9093" in provider_data["endpoints"]
    assert "2182" in provider_data["zookeeper-uris"]
    assert "test-prefix" in provider_data["consumer-group-prefix"]
    assert "test-topic" in provider_data["topic"]
