#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import re
from dataclasses import asdict, dataclass
from typing import List, Optional, Set

from charms.kafka.v0.kafka_snap import KafkaSnap

logger = logging.getLogger(__name__)


@dataclass(unsafe_hash=True)
class Acl:
    resource_name: str
    resource_type: str
    operation: str
    username: str


class KafkaAuth:
    def __init__(self, opts: List[str], zookeeper: str):
        self.opts = opts
        self.zookeeper = zookeeper
        self.current_acls: Set[Acl] = set()
        self.new_user_acls: Set[Acl] = set()

    def load_current_acls(self) -> None:
        """Gets the bin command for listing topic ACLs.

        Returns:
            List of bin command items
        """
        command = [
            f"--authorizer-properties zookeeper.connect={self.zookeeper}",
            "--list",
        ]

        acls = KafkaSnap.run_bin_command(bin_keyword="acls", bin_args=command, opts=self.opts)

        current_acls = set()
        resource_type, name, user, operation = None, None, None, None
        for line in acls.splitlines():
            search = re.search(r"resourceType=([^\,]+),", line)
            if search:
                resource_type = search[1]

            search = re.search(r"name=([^\,]+),", line)
            if search:
                name = search[1]

            search = re.search(r"principal=User\:([^\,]+),", line)
            if search:
                user = search[1]

            search = re.search(r"operation=([^\,]+),", line)
            if search:
                operation = search[1]
            else:
                continue

            if resource_type and name and user and operation:
                current_acls.add(
                    Acl(
                        resource_type=resource_type,
                        resource_name=name,
                        username=user,
                        operation=operation,
                    )
                )

        self.current_acls = current_acls

    def _generate_producer_acls(self, topic: str, username: str, **_) -> Set[Acl]:
        producer_acls = set()
        for operation in ["CREATE", "WRITE", "DESCRIBE"]:
            producer_acls.add(
                Acl(
                    resource_type="TOPIC",
                    resource_name=topic,
                    username=username,
                    operation=operation,
                )
            )

        return producer_acls

    def _generate_consumer_acls(
        self, topic: str, username: str, group: Optional[str] = None
    ) -> Set[Acl]:
        group = group or f"{username}-"

        consumer_acls = set()
        for operation in ["READ", "DESCRIBE"]:
            consumer_acls.add(
                Acl(
                    resource_type="TOPIC",
                    resource_name=topic,
                    username=username,
                    operation=operation,
                )
            )
        consumer_acls.add(
            Acl(
                resource_type="GROUP",
                resource_name=group,
                username=username,
                operation="READ",
            )
        )

        return consumer_acls

    def add_user(self, username: str, password: str) -> None:
        """Gets the bin command for adding user credentials to ZooKeeper.

        Returns:
            List of bin command items
        """
        command = [
            f"--zookeeper={self.zookeeper}",
            "--alter",
            "--entity-type=users",
            f"--entity-name={username}",
            f"--add-config=SCRAM-SHA-512=[password={password}]",
        ]
        KafkaSnap.run_bin_command(bin_keyword="configs", bin_args=command, opts=self.opts)

    def delete_user(self, username: str) -> None:
        """Gets the bin command for deleting user credentials to ZooKeeper.

        Returns:
            List of bin command items
        """
        command = [
            f"--zookeeper={self.zookeeper}",
            "--alter",
            "--entity-type=users",
            f"--entity-name={username}",
            "--delete-config=SCRAM-SHA-512",
        ]
        KafkaSnap.run_bin_command(bin_keyword="configs", bin_args=command, opts=self.opts)

    def add_acl(
        self, username: str, operation: str, resource_type: str, resource_name: str
    ) -> None:
        """Gets the bin command for adding topic ACLs for a given user.

        Returns:
            List of bin command items
        """
        if resource_type == "TOPIC":
            command = [
                f"--authorizer-properties zookeeper.connect={self.zookeeper}",
                "--add",
                f"--allow-principal=User:{username}",
                f"--operation={operation}",
                f"--topic={resource_name}",
            ]
            KafkaSnap.run_bin_command(bin_keyword="acls", bin_args=command, opts=self.opts)

        if resource_type == "GROUP":
            command = [
                f"--authorizer-properties zookeeper.connect={self.zookeeper}",
                "--add",
                f"--allow-principal=User:{username}",
                f"--operation={operation}",
                f"--group={resource_name}",
                "--resource-pattern-type=PREFIXED",
            ]
            KafkaSnap.run_bin_command(bin_keyword="acls", bin_args=command, opts=self.opts)

    def remove_acl(
        self, username: str, operation: str, resource_type: str, resource_name: str
    ) -> None:
        """Gets the bin command for removing topic ACLs for a given user.

        Returns:
            List of bin command items
        """
        if resource_type == "TOPIC":
            command = [
                f"--authorizer-properties zookeeper.connect={self.zookeeper}",
                "--remove",
                f"--allow-principal=User:{username}",
                f"--operation={operation}",
                f"--topic={resource_name}",
                "--force",
            ]
            KafkaSnap.run_bin_command(bin_keyword="acls", bin_args=command, opts=self.opts)

        if resource_type == "GROUP":
            command = [
                f"--authorizer-properties zookeeper.connect={self.zookeeper}",
                "--remove",
                f"--allow-principal=User:{username}",
                f"--operation={operation}",
                f"--group={resource_name}",
                "--resource-pattern-type=PREFIXED",
                "--force",
            ]
            KafkaSnap.run_bin_command(bin_keyword="acls", bin_args=command, opts=self.opts)

    def update_user_acls(self, username: str, topic: str, extra_user_roles: str, group: str, **_):
        if "producer" in extra_user_roles:
            self.new_user_acls.update(self._generate_producer_acls(topic=topic, username=username))
        if "consumer" in extra_user_roles:
            self.new_user_acls.update(
                self._generate_consumer_acls(topic=topic, username=username, group=group)
            )

        current_user_acls = {acl for acl in self.current_acls if acl.username == username}

        acls_to_add = self.new_user_acls - current_user_acls
        for acl in acls_to_add:
            self.add_acl(**asdict(acl))

        acls_to_remove = current_user_acls - self.new_user_acls
        for acl in acls_to_remove:
            self.remove_acl(**asdict(acl))
