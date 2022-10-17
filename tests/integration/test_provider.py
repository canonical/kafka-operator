#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from pytest_operator.plugin import OpsTest

from tests.integration.helpers import (
    check_user,
    get_provider_data,
    get_zookeeper_connection,
    load_acls,
    load_super_users,
)

logger = logging.getLogger(__name__)

APP_NAME = "kafka"
ZK = "zookeeper"
DUMMY_NAME_1 = "app"
DUMMY_NAME_2 = "appii"
TLS_NAME = "tls-certificates-operator"


@pytest.fixture(scope="module")
def usernames():
    return set()


@pytest.mark.abort_on_fail
async def test_deploy_charms_relate_active(ops_test: OpsTest, usernames):
    charm = await ops_test.build_charm(".")
    app_charm = await ops_test.build_charm("tests/integration/app-charm")

    await asyncio.gather(
        ops_test.model.deploy(
            "zookeeper", channel="edge", application_name="zookeeper", num_units=3
        ),
        ops_test.model.deploy(charm, application_name=APP_NAME, num_units=1),
        ops_test.model.deploy(app_charm, application_name=DUMMY_NAME_1, num_units=1),
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME_1, ZK])
    await ops_test.model.add_relation(APP_NAME, ZK)
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK])
    await ops_test.model.add_relation(APP_NAME, DUMMY_NAME_1)
    await ops_test.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME_1])
    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[DUMMY_NAME_1].status == "active"

    # implicitly tests setting of kafka app data
    returned_usernames, zookeeper_uri = get_zookeeper_connection(
        unit_name="kafka/0", model_full_name=ops_test.model_full_name
    )
    usernames.update(returned_usernames)

    for username in usernames:
        check_user(
            username=username,
            zookeeper_uri=zookeeper_uri,
            model_full_name=ops_test.model_full_name,
        )

    for acl in load_acls(model_full_name=ops_test.model_full_name, zookeeper_uri=zookeeper_uri):
        assert acl.username in usernames
        assert acl.operation in ["READ", "DESCRIBE"]
        assert acl.resource_type in ["GROUP", "TOPIC"]
        if acl.resource_type == "TOPIC":
            assert acl.resource_name == "test-topic"


@pytest.mark.abort_on_fail
async def test_deploy_multiple_charms_same_topic_relate_active(ops_test: OpsTest, usernames):
    appii_charm = await ops_test.build_charm("tests/integration/app-charm")
    await ops_test.model.deploy(appii_charm, application_name=DUMMY_NAME_2, num_units=1),
    await ops_test.model.wait_for_idle(apps=[DUMMY_NAME_2])
    await ops_test.model.add_relation(APP_NAME, DUMMY_NAME_2)
    await ops_test.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME_2])
    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[DUMMY_NAME_1].status == "active"
    assert ops_test.model.applications[DUMMY_NAME_2].status == "active"

    returned_usernames, zookeeper_uri = get_zookeeper_connection(
        unit_name="kafka/0", model_full_name=ops_test.model_full_name
    )
    usernames.update(returned_usernames)

    for username in usernames:
        check_user(
            username=username,
            zookeeper_uri=zookeeper_uri,
            model_full_name=ops_test.model_full_name,
        )

    for acl in load_acls(model_full_name=ops_test.model_full_name, zookeeper_uri=zookeeper_uri):
        assert acl.username in usernames
        assert acl.operation in ["READ", "DESCRIBE"]
        assert acl.resource_type in ["GROUP", "TOPIC"]
        if acl.resource_type == "TOPIC":
            assert acl.resource_name == "test-topic"


@pytest.mark.abort_on_fail
async def test_remove_application_removes_user_and_acls(ops_test: OpsTest, usernames):
    await ops_test.model.remove_application(DUMMY_NAME_1, block_until_done=True)
    await ops_test.model.wait_for_idle(apps=[APP_NAME])
    assert ops_test.model.applications[APP_NAME].status == "active"

    _, zookeeper_uri = get_zookeeper_connection(
        unit_name="kafka/0", model_full_name=ops_test.model_full_name
    )

    # checks that old users are removed from active cluster ACLs
    acls = load_acls(model_full_name=ops_test.model_full_name, zookeeper_uri=zookeeper_uri)
    acl_usernames = set()
    for acl in acls:
        acl_usernames.add(acl.username)

    assert acl_usernames != usernames

    # checks that past usernames no longer exist in ZooKeeper
    with pytest.raises(AssertionError):
        for username in usernames:
            check_user(
                username=username,
                zookeeper_uri=zookeeper_uri,
                model_full_name=ops_test.model_full_name,
            )


@pytest.mark.abort_on_fail
async def test_change_client_topic(ops_test: OpsTest):
    action = await ops_test.model.units.get(f"{DUMMY_NAME_2}/0").run_action("change-topic")
    await action.wait()
    assert ops_test.model.applications[APP_NAME].status == "active"
    await ops_test.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME_2])

    _, zookeeper_uri = get_zookeeper_connection(
        unit_name="kafka/0", model_full_name=ops_test.model_full_name
    )

    for acl in load_acls(model_full_name=ops_test.model_full_name, zookeeper_uri=zookeeper_uri):
        if acl.resource_type == "TOPIC":
            assert acl.resource_name == "test-topic-changed"


@pytest.mark.abort_on_fail
async def test_admin_added_to_super_users(ops_test: OpsTest):
    # ensures only broker user for now
    super_users = load_super_users(model_full_name=ops_test.model_full_name)
    assert len(super_users) == 1

    action = await ops_test.model.units.get(f"{DUMMY_NAME_2}/0").run_action("make-admin")
    await action.wait()

    await ops_test.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME_2])
    assert ops_test.model.applications[APP_NAME].status == "active"

    super_users = load_super_users(model_full_name=ops_test.model_full_name)
    assert len(super_users) == 2


@pytest.mark.abort_on_fail
async def test_admin_removed_from_super_users(ops_test: OpsTest):
    action = await ops_test.model.units.get(f"{DUMMY_NAME_2}/0").run_action("remove-admin")
    await action.wait()

    await ops_test.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME_2])
    assert ops_test.model.applications[APP_NAME].status == "active"

    super_users = load_super_users(model_full_name=ops_test.model_full_name)
    assert len(super_users) == 1


@pytest.mark.abort_on_fail
async def test_connection_updated_on_tls_enabled(ops_test: OpsTest):
    tls_config = {"generate-self-signed-certificates": "true", "ca-common-name": "kafka"}
    await ops_test.model.deploy(TLS_NAME, channel="edge", config=tls_config)
    await ops_test.model.add_relation(TLS_NAME, ZK)
    await ops_test.model.add_relation(TLS_NAME, APP_NAME)

    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK, TLS_NAME], timeout=1000, idle_period=40)

    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[ZK].status == "active"
    assert ops_test.model.applications[TLS_NAME].status == "active"

    # Check that related application has updated information
    provider_data = get_provider_data(
        unit_name="appii/0", model_full_name=ops_test.model_full_name
    )

    assert provider_data["tls"] == "enabled"
    assert "9093" in provider_data["uris"]
    assert "2182" in provider_data["zookeeper-uris"]
