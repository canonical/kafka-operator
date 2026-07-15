#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time
from pathlib import PosixPath
from typing import Set

import jubilant
import pytest
from single_kernel_kafka.core.literals import TLS_RELATION

from integration.k8s.helpers import TLS_CHANNEL, TLS_NAME
from integration.k8s.helpers.jubilant import all_active_idle, deploy_cluster, fast_forward
from integration.k8s.helpers.legacy import (
    APP_NAME,
    REL_NAME_ADMIN,
    check_user,
    get_client_usernames,
    get_node_port,
    get_provider_data,
    load_acls,
    load_super_users,
    netcat,
)

logger = logging.getLogger(__name__)

DUMMY_NAME_1 = "app"
DUMMY_NAME_2 = "appii"
REL_NAME_CONSUMER = "kafka-client-consumer"
REL_NAME_PRODUCER = "kafka-client-producer"


def test_deploy_charms_relate_active(
    juju: jubilant.Juju,
    kafka_charm,
    app_charm: PosixPath,
    usernames: Set[str],
    kraft_mode,
    kafka_apps,
):
    """Test deploy and relate operations."""
    deploy_cluster(
        juju=juju,
        charm=kafka_charm,
        kraft_mode=kraft_mode,
        config_broker={"expose-external": "nodeport"},
        num_controller=3,
    )
    juju.deploy(app_charm, app=DUMMY_NAME_1, num_units=1, trust=True)
    juju.integrate(APP_NAME, f"{DUMMY_NAME_1}:{REL_NAME_CONSUMER}")

    with fast_forward(juju, fast_interval="60s"):
        juju.wait(
            lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME_1),
            delay=10,
            successes=3,
            timeout=2000,
        )

    usernames.update(get_client_usernames(juju))

    for username in usernames:
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
    juju: jubilant.Juju, app_charm: PosixPath, usernames: Set[str], kafka_apps
):
    """Test relation with multiple applications."""
    juju.deploy(app_charm, app=DUMMY_NAME_2, num_units=1, trust=True)
    juju.integrate(APP_NAME, f"{DUMMY_NAME_2}:{REL_NAME_CONSUMER}")

    with fast_forward(juju, fast_interval="60s"):
        juju.wait(
            lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME_1),
            delay=10,
            successes=3,
            timeout=600,
        )

    usernames.update(get_client_usernames(juju))
    for username in usernames:
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
    juju: jubilant.Juju, usernames: Set[str], kafka_apps
):
    """Test the correct removal of user and permission after relation removal."""
    juju.remove_application(DUMMY_NAME_1)

    with fast_forward(juju, fast_interval="60s"):
        juju.wait(
            lambda status: DUMMY_NAME_1 not in status.apps
            and all_active_idle(status, *kafka_apps),
            delay=10,
            successes=3,
            timeout=600,
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
    juju: jubilant.Juju, app_charm: PosixPath, usernames: Set[str], kafka_apps
):
    """Test the correct deployment and relation with role producer."""
    juju.deploy(
        app_charm,
        app=DUMMY_NAME_1,
        num_units=1,
        trust=True,
    )
    juju.integrate(APP_NAME, f"{DUMMY_NAME_1}:{REL_NAME_PRODUCER}")

    with fast_forward(juju, fast_interval="60s"):
        juju.wait(
            lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME_1),
            delay=10,
            successes=3,
            timeout=600,
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
    juju.wait(
        lambda status: DUMMY_NAME_1 not in status.apps and all_active_idle(status, *kafka_apps),
        delay=10,
        successes=3,
        timeout=600,
    )


def test_admin_added_to_super_users(juju: jubilant.Juju, app_charm, kafka_apps):
    """Test relation with admin privileges."""
    super_users = load_super_users(model_full_name=juju.model)
    assert len(super_users) == 3  # controller, replication, operator

    juju.deploy(
        app_charm,
        app=DUMMY_NAME_1,
        num_units=1,
        trust=True,
    )
    juju.integrate(APP_NAME, f"{DUMMY_NAME_1}:{REL_NAME_ADMIN}")
    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME_1),
        delay=10,
        successes=3,
        timeout=600,
    )

    # check the correct addition of super-users
    super_users = load_super_users(model_full_name=juju.model)
    assert len(super_users) == 4


def test_admin_removed_from_super_users(juju: jubilant.Juju, kafka_apps):
    """Test that removal of the relation with admin privileges."""
    juju.remove_application(DUMMY_NAME_1)
    juju.wait(
        lambda status: DUMMY_NAME_1 not in status.apps
        and all_active_idle(status, *kafka_apps, DUMMY_NAME_2),
        delay=10,
        successes=3,
        timeout=900,
    )

    assert juju.status().apps[APP_NAME].app_status.current == "active"

    super_users = load_super_users(model_full_name=juju.model)
    assert len(super_users) == 3

    # adding cleanup to save memory
    juju.remove_application(DUMMY_NAME_2)
    juju.wait(
        lambda status: DUMMY_NAME_2 not in status.apps and all_active_idle(status, *kafka_apps),
        delay=10,
        successes=3,
        timeout=600,
    )


def test_connection_updated_on_tls_enabled(juju: jubilant.Juju, app_charm: PosixPath, kafka_apps):
    """Test relation when TLS is enabled."""
    # adding new app unit to validate
    juju.deploy(app_charm, app=DUMMY_NAME_1, num_units=1, trust=True)
    juju.integrate(APP_NAME, f"{DUMMY_NAME_1}:{REL_NAME_CONSUMER}")
    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME_1),
        delay=10,
        successes=3,
        timeout=600,
    )

    # deploying tls
    tls_config = {"ca-common-name": "kafka"}
    # FIXME (certs): Unpin the revision once the charm is fixed
    juju.deploy(TLS_NAME, channel=TLS_CHANNEL, config=tls_config, trust=True)
    juju.wait(all_active_idle, timeout=1800, delay=3, successes=10)

    # relating tls with kafka
    juju.integrate(TLS_NAME, f"{APP_NAME}:{TLS_RELATION}")
    juju.wait(all_active_idle, timeout=1800, delay=3, successes=20)

    # ensure at least one update-status run
    with fast_forward(juju, fast_interval="30s"):
        time.sleep(60)

    juju.wait(all_active_idle, timeout=1800, delay=3, successes=10)

    # Check that related application has updated information
    provider_data = get_provider_data(
        juju=juju,
        unit_name=f"{DUMMY_NAME_1}/0",
        relation_interface="kafka-client-consumer",
        owner=APP_NAME,
    )

    tls_bootstrap_port = str(get_node_port(juju, APP_NAME, "sasl-ssl-scram-bootstrap-port"))

    assert provider_data["tls"] == "enabled"
    assert tls_bootstrap_port in provider_data["endpoints"]
    assert "test-prefix" in provider_data["consumer-group-prefix"]
    assert "test-topic" in provider_data["topic"]
    assert len(provider_data["endpoints"].split(",")) == 1  # aka single bootstrap service returned

    provided_host, provided_port = provider_data["endpoints"].split(":")

    assert netcat(provided_host, int(provided_port))
