#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from unittest.mock import Mock

import pytest

from managers.auth import Acl, AuthManager
from workload import KafkaWorkload

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker


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


def test_add_user_adds_zk_tls_flag(monkeypatch) -> None:
    """Checks zk-tls-config-file flag is called for configs bin command."""
    # Given
    state = Mock()
    state.zookeeper.connect = "host"
    workload = KafkaWorkload(container=Mock())
    patched_exec = Mock()
    monkeypatch.setattr(workload, "run_bin_command", patched_exec)
    auth_manager = AuthManager(state, workload, "", "")

    # When
    auth_manager.add_user("samwise", "gamgee", zk_auth=True)
    args = patched_exec.call_args_list[0][1]

    # Then
    assert (
        f"--zk-tls-config-file={workload.paths.server_properties}" in args["bin_args"]
    ), "--zk-tls-config-file flag not found"
    assert "--zookeeper=host" in args["bin_args"], "--zookeeper flag not found"
