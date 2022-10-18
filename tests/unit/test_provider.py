#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path
from unittest.mock import PropertyMock, patch

import pytest
import yaml
from ops.testing import Harness

from charm import KafkaCharm
from literals import CHARM_KEY, PEER, REL_NAME

logger = logging.getLogger(__name__)

CONFIG = str(yaml.safe_load(Path("./config.yaml").read_text()))
ACTIONS = str(yaml.safe_load(Path("./actions.yaml").read_text()))
METADATA = str(yaml.safe_load(Path("./metadata.yaml").read_text()))


@pytest.fixture
def harness():
    harness = Harness(KafkaCharm, meta=METADATA)
    harness.add_relation("restart", CHARM_KEY)
    harness._update_config(
        {
            "offsets-retention-minutes": 10080,
            "log-retention-hours": 168,
            "auto-create-topics": False,
        }
    )

    harness.begin()
    return harness


def test_client_relation_created_defers_if_not_ready(harness):
    with harness.hooks_disabled():
        harness.add_relation(PEER, CHARM_KEY)

    with patch(
        "charm.KafkaCharm.ready_to_start", new_callable=PropertyMock, return_value=False
    ), patch("auth.KafkaAuth.add_user") as patched:
        harness.set_leader(True)
        harness.add_relation(REL_NAME, "app")

        patched.assert_not_called()


def test_client_relation_created_adds_user(harness):
    harness.add_relation(PEER, CHARM_KEY)
    with patch(
        "charm.KafkaCharm.ready_to_start", new_callable=PropertyMock, return_value=True
    ), patch("auth.KafkaAuth.add_user") as patched:
        harness.set_leader(True)
        client_rel_id = harness.add_relation(REL_NAME, "app")

        patched.assert_called_once()

        assert harness.charm.peer_relation.data[harness.charm.app].get(f"relation-{client_rel_id}")


def test_client_relation_broken_removes_user(harness):
    harness.add_relation(PEER, CHARM_KEY)
    with patch(
        "charm.KafkaCharm.ready_to_start", new_callable=PropertyMock, return_value=True
    ), patch("auth.KafkaAuth.add_user"), patch(
        "auth.KafkaAuth.delete_user"
    ) as patched_delete, patch(
        "auth.KafkaAuth.remove_all_user_acls"
    ) as patched_remove_acls, patch(
        "snap.KafkaSnap.run_bin_command"
    ):
        harness.set_leader(True)
        client_rel_id = harness.add_relation(REL_NAME, "app")

        # validating username got added
        assert harness.charm.peer_relation.data[harness.charm.app].get(f"relation-{client_rel_id}")

        harness.remove_relation(client_rel_id)

        # validating username got removed
        assert not harness.charm.peer_relation.data[harness.charm.app].get(
            f"relation-{client_rel_id}"
        )
        patched_remove_acls.assert_called_once()
        patched_delete.assert_called_once()


def test_client_relation_joined_sets_necessary_relation_data(harness):
    harness.add_relation(PEER, CHARM_KEY)
    with patch(
        "charm.KafkaCharm.ready_to_start", new_callable=PropertyMock, return_value=True
    ), patch("auth.KafkaAuth.add_user"), patch("snap.KafkaSnap.run_bin_command"), patch(
        "config.KafkaConfig.zookeeper_connected", new_callable=PropertyMock, return_value=True
    ), patch(
        "config.KafkaConfig.zookeeper_config",
        new_callable=PropertyMock,
        return_value={"connect": "yes"},
    ):
        harness.set_leader(True)
        client_rel_id = harness.add_relation(REL_NAME, "app")
        client_relation = harness.charm.model.relations[REL_NAME][0]

        harness.update_relation_data(client_relation.id, "app", {"extra-user-roles": "consumer"})
        harness.add_relation_unit(client_rel_id, "app/0")

        assert sorted(
            [
                "username",
                "password",
                "endpoints",
                "uris",
                "zookeeper-uris",
                "consumer-group-prefix",
                "tls",
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