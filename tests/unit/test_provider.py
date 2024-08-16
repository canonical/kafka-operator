#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path
from unittest.mock import PropertyMock, patch

import pytest
import yaml
from ops.testing import Harness

from charm import KafkaCharm
from literals import CHARM_KEY, CONTAINER, PEER, REL_NAME, SUBSTRATE

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker

CONFIG = str(yaml.safe_load(Path("./config.yaml").read_text()))
ACTIONS = str(yaml.safe_load(Path("./actions.yaml").read_text()))
METADATA = str(yaml.safe_load(Path("./metadata.yaml").read_text()))


@pytest.fixture
def harness():
    harness = Harness(KafkaCharm, meta=METADATA, actions=ACTIONS, config=CONFIG)

    if SUBSTRATE == "k8s":
        harness.set_can_connect(CONTAINER, True)

    harness.add_relation("restart", CHARM_KEY)
    harness._update_config(
        {
            "log_retention_ms": "-1",
            "compression_type": "producer",
            "expose-external": "none",
        }
    )

    harness.begin()
    return harness


def test_client_relation_created_defers_if_not_ready(harness: Harness[KafkaCharm]):
    """Checks event is deferred if not ready on clientrelationcreated hook."""
    with harness.hooks_disabled():
        harness.add_relation(PEER, CHARM_KEY)

    with (
        patch(
            "events.broker.BrokerOperator.healthy", new_callable=PropertyMock, return_value=False
        ),
        patch("managers.auth.AuthManager.add_user") as patched_add_user,
        patch("ops.framework.EventBase.defer") as patched_defer,
    ):
        harness.set_leader(True)
        client_rel_id = harness.add_relation(REL_NAME, "app")
        # update relation to trigger on_topic_requested event
        harness.update_relation_data(
            client_rel_id,
            "app",
            {"topic": "TOPIC", "extra-user-roles": "consumer,producer"},
        )

        patched_add_user.assert_not_called()
        patched_defer.assert_called()


def test_client_relation_created_adds_user(harness: Harness[KafkaCharm]):
    """Checks if new users are added on clientrelationcreated hook."""
    with harness.hooks_disabled():
        harness.add_relation(PEER, CHARM_KEY)
        harness.set_leader(True)
        client_rel_id = harness.add_relation(REL_NAME, "app")

    with (
        patch(
            "events.broker.BrokerOperator.healthy", new_callable=PropertyMock, return_value=True
        ),
        patch("managers.auth.AuthManager.add_user") as patched_add_user,
        patch("workload.KafkaWorkload.run_bin_command"),
        patch("core.cluster.ZooKeeper.connect", new_callable=PropertyMock, return_value="yes"),
    ):
        harness.update_relation_data(
            client_rel_id,
            "app",
            {"topic": "TOPIC", "extra-user-roles": "consumer,producer"},
        )

        patched_add_user.assert_called_once()
        assert harness.charm.state.cluster.relation_data.get(f"relation-{client_rel_id}")


def test_client_relation_broken_removes_user(harness: Harness[KafkaCharm]):
    """Checks if users are removed on clientrelationbroken hook."""
    with harness.hooks_disabled():
        harness.add_relation(PEER, CHARM_KEY)

    with (
        patch(
            "events.broker.BrokerOperator.healthy", new_callable=PropertyMock, return_value=True
        ),
        patch("managers.auth.AuthManager.add_user"),
        patch("managers.auth.AuthManager.delete_user") as patched_delete_user,
        patch("managers.auth.AuthManager.remove_all_user_acls") as patched_remove_acls,
        patch("workload.KafkaWorkload.run_bin_command"),
        patch("core.cluster.ZooKeeper.connect", new_callable=PropertyMock, return_value="yes"),
    ):
        harness.set_leader(True)
        client_rel_id = harness.add_relation(REL_NAME, "app")
        harness.update_relation_data(
            client_rel_id,
            "app",
            {"topic": "TOPIC", "extra-user-roles": "consumer,producer"},
        )

        # validating username got added
        assert harness.charm.state.cluster.relation_data.get(f"relation-{client_rel_id}")

        harness.remove_relation(client_rel_id)

        # validating username got removed
        assert not harness.charm.state.cluster.relation_data.get(f"relation-{client_rel_id}")
        patched_remove_acls.assert_called_once()
        patched_delete_user.assert_called_once()


def test_client_relation_joined_sets_necessary_relation_data(harness: Harness[KafkaCharm]):
    """Checks if all needed provider relation data is set on clientrelationjoined hook."""
    with harness.hooks_disabled():
        harness.add_relation(PEER, CHARM_KEY)

    with (
        patch(
            "events.broker.BrokerOperator.healthy", new_callable=PropertyMock, return_value=True
        ),
        patch("managers.auth.AuthManager.add_user"),
        patch("workload.KafkaWorkload.run_bin_command"),
        patch("core.models.ZooKeeper.uris", new_callable=PropertyMock, return_value="yes"),
    ):
        harness.set_leader(True)
        client_rel_id = harness.add_relation(REL_NAME, "app")
        client_relation = harness.charm.model.relations[REL_NAME][0]

        harness.update_relation_data(
            client_relation.id, "app", {"topic": "TOPIC", "extra-user-roles": "consumer"}
        )
        harness.add_relation_unit(client_rel_id, "app/0")
        assert sorted(
            [
                "username",
                "password",
                "tls-ca",
                "endpoints",
                "data",
                "zookeeper-uris",
                "consumer-group-prefix",
                "tls",
                "topic",
            ]
        ) == sorted(client_relation.data[harness.charm.app].keys())

        assert client_relation.data[harness.charm.app].get("tls", None) == "disabled"
        assert client_relation.data[harness.charm.app].get("zookeeper-uris", None) == "yes"
        assert (
            client_relation.data[harness.charm.app].get("username", None)
            == f"relation-{client_rel_id}"
        )
        assert (
            client_relation.data[harness.charm.app].get("consumer-group-prefix", None)
            == f"relation-{client_rel_id}-"
        )
