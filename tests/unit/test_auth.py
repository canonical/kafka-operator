#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from ops.testing import Harness

from charm import KafkaCharm
from literals import CHARM_KEY, CONTAINER, SUBSTRATE
from managers.auth import Acl, AuthManager

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker

CONFIG = str(yaml.safe_load(Path("./config.yaml").read_text()))
ACTIONS = str(yaml.safe_load(Path("./actions.yaml").read_text()))
METADATA = str(yaml.safe_load(Path("./metadata.yaml").read_text()))


@pytest.fixture
def harness():
    harness = Harness(KafkaCharm, meta=METADATA)

    if SUBSTRATE == "k8s":
        harness.set_can_connect(CONTAINER, True)

    harness.add_relation("restart", CHARM_KEY)
    harness._update_config(
        {
            "log_retention_ms": "-1",
            "compression_type": "producer",
        }
    )

    harness.begin()
    return harness


def test_acl():
    assert sorted(Acl.__annotations__.keys()) == sorted(
        ["operation", "resource_name", "resource_type", "username"]
    )
    assert Acl.__hash__


def test_parse_acls():
    """Checks that returned ACL message is parsed correctly into Acl object."""
    acls = """
    Current ACLs for resource `ResourcePattern(resourceType=GROUP, name=relation-81-*, patternType=LITERAL)`:
        (principal=User:relation-81, host=*, operation=READ, permissionType=ALLOW)

    Current ACLs for resource `ResourcePattern(resourceType=TOPIC, name=test-topic, patternType=LITERAL)`:
        (principal=User:relation-81, host=*, operation=WRITE, permissionType=ALLOW)
        (principal=User:relation-81, host=*, operation=CREATE, permissionType=ALLOW)
        (principal=User:relation-81, host=*, operation=DESCRIBE, permissionType=ALLOW)
        (principal=User:relation-81, host=*, operation=READ, permissionType=ALLOW)
    """

    parsed_acls = AuthManager._parse_acls(acls=acls)

    assert len(parsed_acls) == 5
    assert type(list(parsed_acls)[0]) is Acl


def test_generate_producer_acls():
    """Checks correct resourceType for producer ACLs."""
    generated_acls = AuthManager._generate_producer_acls(topic="theonering", username="frodo")
    assert len(generated_acls) == 3

    operations = set()
    resource_types = set()
    for acl in generated_acls:
        operations.add(acl.operation)
        resource_types.add(acl.resource_type)

    assert sorted(operations) == sorted({"CREATE", "WRITE", "DESCRIBE"})
    assert resource_types == {"TOPIC"}


def test_generate_consumer_acls():
    """Checks correct resourceType for consumer ACLs."""
    generated_acls = AuthManager._generate_consumer_acls(topic="theonering", username="frodo")
    assert len(generated_acls) == 3

    operations = set()
    resource_types = set()
    for acl in generated_acls:
        operations.add(acl.operation)
        resource_types.add(acl.resource_type)

        if acl.resource_type == "GROUP":
            assert acl.operation == "READ"

    assert sorted(operations) == sorted({"READ", "DESCRIBE"})
    assert sorted(resource_types) == sorted({"TOPIC", "GROUP"})


def test_add_user_adds_zk_tls_flag(harness: Harness[KafkaCharm]):
    """Checks zk-tls-config-file flag is called for configs bin command."""
    with patch("workload.KafkaWorkload.run_bin_command") as patched_exec:
        harness.charm.broker.auth_manager.add_user("samwise", "gamgee", zk_auth=True)
        args = patched_exec.call_args_list[0][1]

        assert (
            f"--zk-tls-config-file={harness.charm.workload.paths.server_properties}"
            in args["bin_args"]
        ), "--zk-tls-config-file flag not found"
        assert "--zookeeper=" in args["bin_args"], "--zookeeper flag not found"


def test_prefixed_acls(harness: Harness[KafkaCharm]):
    """Checks the requirements for adding and removing PREFIXED ACLs."""
    with patch("workload.KafkaWorkload.run_bin_command") as patched_run_bin:
        for func in [
            harness.charm.broker.auth_manager.add_acl,
            harness.charm.broker.auth_manager.remove_acl,
        ]:
            func(
                username="bilbo",
                operation="WRITE",
                resource_type="TOPIC",
                resource_name="there-and-back-again",
            )
            func(
                username="bilbo",
                operation="WRITE",
                resource_type="TOPIC",
                resource_name="there-and-back-*",
            )
            func(username="bilbo", operation="WRITE", resource_type="TOPIC", resource_name="??*")

            assert (
                "--resource-pattern-type=LITERAL"
                in patched_run_bin.call_args_list[0].kwargs["bin_args"]
            )

            assert (
                "--resource-pattern-type=PREFIXED"
                in patched_run_bin.call_args_list[1].kwargs["bin_args"]
            )

            # checks that the prefixed topic removes the '*' char from the end
            assert (
                "--topic=there-and-back-" in patched_run_bin.call_args_list[1].kwargs["bin_args"]
            )

            assert (
                "--resource-pattern-type=LITERAL"
                in patched_run_bin.call_args_list[2].kwargs["bin_args"]
            )
