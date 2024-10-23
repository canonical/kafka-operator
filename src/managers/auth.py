#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Supporting objects for Kafka user and ACL management."""

import logging
import re
import subprocess  # nosec B404
from dataclasses import asdict, dataclass

from ops.pebble import ExecError

from core.cluster import ClusterState
from core.workload import WorkloadBase
from literals import SECURITY_PROTOCOL_PORTS

logger = logging.getLogger(__name__)


@dataclass(unsafe_hash=True)
class Acl:
    """Convenience object for representing a Kafka ACL."""

    resource_name: str
    resource_type: str
    operation: str
    username: str


class AuthManager:
    """Object for updating Kafka users and ACLs."""

    def __init__(
        self, state: ClusterState, workload: WorkloadBase, kafka_opts: str, log4j_opts: str
    ):
        self.state = state
        self.workload = workload
        self.kafka_opts = kafka_opts
        self.log4j_opts = log4j_opts
        self.new_user_acls: set[Acl] = set()

    @property
    def current_acls(self) -> set[Acl]:
        """Sets the current cluster ACLs."""
        acls = self._get_acls_from_cluster()
        return self._parse_acls(acls=acls)

    def _get_acls_from_cluster(self) -> str:
        """Loads the currently active ACLs from the Kafka cluster."""
        command = [
            f"--bootstrap-server={self.state.bootstrap_server}",
            f"--command-config={self.workload.paths.client_properties}",
            "--list",
        ]
        acls = self.workload.run_bin_command(
            bin_keyword="acls", bin_args=command, opts=[self.log4j_opts]
        )

        return acls

    @staticmethod
    def _parse_acls(acls: str) -> set[Acl]:
        """Parses output from raw ACLs provided by the cluster."""
        current_acls = set()
        resource_type, name, user, operation = None, None, None, None
        for line in acls.splitlines():
            resource_search = re.search(r"resourceType=([^\,]+),", line)
            if resource_search:
                resource_type = resource_search[1]

            name_search = re.search(r"name=([^\,]+),", line)
            if name_search:
                name = name_search[1]

            user_search = re.search(r"principal=User\:([^\,]+),", line)
            if user_search:
                user = user_search[1]

            operation_search = re.search(r"operation=([^\,]+),", line)
            if operation_search:
                operation = operation_search[1]
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

        return current_acls

    @staticmethod
    def _generate_producer_acls(topic: str, username: str, **_) -> set[Acl]:
        """Generates expected set of `Acl`s for a producer client application."""
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

    @staticmethod
    def _generate_consumer_acls(topic: str, username: str, group: str | None = None) -> set[Acl]:
        """Generates expected set of `Acl`s for a consumer client application."""
        group = group or f"{username}-"  # not needed, just for safety

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

    def add_user(
        self, username: str, password: str, zk_auth: bool = False, internal: bool = False
    ) -> None:
        """Adds new user credentials to ZooKeeper.

        Args:
            username: the user name to add
            password: the user password
            zk_auth: flag to specify adding users using ZooKeeper authorizer
                For use before cluster start
            internal: flag to use internal ports or client ones

        Raises:
            `(subprocess.CalledProcessError | ops.pebble.ExecError)`: if the error returned a non-zero exit code
        """
        base_command = [
            "--alter",
            "--entity-type=users",
            f"--entity-name={username}",
            f"--add-config=SCRAM-SHA-512=[password={password}]",
        ]

        # needed only here, as internal SCRAM users cannot be created using `--bootstrap-server` until the cluster has initialised
        # instead must be authorized using ZooKeeper JAAS
        if zk_auth:
            command = base_command + [
                f"--zookeeper={self.state.zookeeper.connect}",
                f"--zk-tls-config-file={self.workload.paths.server_properties}",
            ]
            opts = [self.kafka_opts]
        else:
            bootstrap_server = (
                f"{self.state.unit_broker.internal_address}:{SECURITY_PROTOCOL_PORTS[self.state.default_auth].internal}"
                if internal
                else self.state.bootstrap_server
            )
            command = base_command + [
                f"--bootstrap-server={bootstrap_server}",
                f"--command-config={self.workload.paths.client_properties}",
            ]
            opts = []

        self.workload.run_bin_command(
            bin_keyword="configs", bin_args=command, opts=opts + [self.log4j_opts]
        )

    def delete_user(self, username: str) -> None:
        """Deletes user credentials from ZooKeeper.

        Args:
            username: the user name to delete

        Raises:
            `(subprocess.CalledProcessError | ops.pebble.ExecError)`: if the error returned a non-zero exit code
        """
        command = [
            f"--bootstrap-server={self.state.bootstrap_server}",
            f"--command-config={self.workload.paths.client_properties}",
            "--alter",
            "--entity-type=users",
            f"--entity-name={username}",
            "--delete-config=SCRAM-SHA-512",
        ]
        try:
            self.workload.run_bin_command(
                bin_keyword="configs", bin_args=command, opts=[self.log4j_opts]
            )
        except (subprocess.CalledProcessError, ExecError) as e:
            if e.stderr and "delete a user credential that does not exist" in e.stderr:
                logger.warning(f"User: {username} can't be deleted, it does not exist")
                return
            raise

    def add_acl(
        self, username: str, operation: str, resource_type: str, resource_name: str
    ) -> None:
        """Adds new ACL rule for the cluster.

        Consumer Group READ permissions are granted to a prefixed group based on the
        given `username`. e.g `<username>-`

        Args:
            username: the user name to add ACLs for
            operation: the operation to grant
                e.g `READ`, `WRITE`, `DESCRIBE`
            resource_type: the resource type to grant ACLs for
                e.g `GROUP`, `TOPIC`
            resource_name: the name of the resource to grant ACLs for

        Raises:
            `(subprocess.CalledProcessError | ops.pebble.ExecError)`: if the error returned a non-zero exit code
        """
        command = [
            f"--bootstrap-server={self.state.bootstrap_server}",
            f"--command-config={self.workload.paths.client_properties}",
            "--add",
            f"--allow-principal=User:{username}",
            f"--operation={operation}",
        ]

        if resource_type == "TOPIC":
            if len(resource_name) > 3 and resource_name.endswith("*"):
                pattern = "PREFIXED"
                resource_name = resource_name[:-1]
            else:
                pattern = "LITERAL"

            command += [f"--topic={resource_name}", f"--resource-pattern-type={pattern}"]

        if resource_type == "GROUP":
            command += [
                f"--group={resource_name}",
                "--resource-pattern-type=PREFIXED",
            ]
        logger.info(f"CREATE ACL - {command}")
        self.workload.run_bin_command(bin_keyword="acls", bin_args=command, opts=[self.log4j_opts])

    def remove_acl(
        self, username: str, operation: str, resource_type: str, resource_name: str
    ) -> None:
        """Removes ACL rule for the cluster.

        Args:
            username: the user name to remove ACLs for
            operation: the operation to remove
                e.g `READ`, `WRITE`, `DESCRIBE`
            resource_type: the resource type to remove ACLs for
                e.g `GROUP`, `TOPIC`
            resource_name: the name of the resource to remove ACLs for

        Raises:
            `(subprocess.CalledProcessError | ops.pebble.ExecError)`: if the error returned a non-zero exit code
        """
        command = [
            f"--bootstrap-server={self.state.bootstrap_server}",
            f"--command-config={self.workload.paths.client_properties}",
            "--remove",
            f"--allow-principal=User:{username}",
            f"--operation={operation}",
            "--force",
        ]

        if resource_type == "TOPIC":
            if len(resource_name) > 3 and resource_name.endswith("*"):
                pattern = "PREFIXED"
                resource_name = resource_name[:-1]
            else:
                pattern = "LITERAL"

            command += [f"--topic={resource_name}", f"--resource-pattern-type={pattern}"]

        if resource_type == "GROUP":
            command += [
                f"--group={resource_name}",
                "--resource-pattern-type=PREFIXED",
            ]

        self.workload.run_bin_command(bin_keyword="acls", bin_args=command, opts=[self.log4j_opts])

    def remove_all_user_acls(self, username: str) -> None:
        """Removes all active ACLs for a given user.

        Args:
            username: the user name to remove ACLs for

        Raises:
            `(subprocess.CalledProcessError | ops.pebble.ExecError)`: if the error returned a non-zero exit code
        """
        # getting subset of all cluster ACLs for only the provided user
        current_user_acls = {acl for acl in self.current_acls if acl.username == username}

        for acl in current_user_acls:
            self.remove_acl(**asdict(acl))

    def update_user_acls(
        self, username: str, topic: str, extra_user_roles: str, group: str | None, **_
    ) -> None:
        """Compares data passed from the client relation, and updating cluster ACLs to match.

        `producer`s are granted READ, DESCRIBE and WRITE access for a given topic
        `consumer`s are granted READ, DESCRIBE access for a given topic, and READ access for a
            generated consumer group

        If new ACLs provided do not match existing ACLs set for the cluster, existing ACLs will
            be revoked

        Args:
            username: the user name to update ACLs for
            topic: the topic to update ACLs for
            extra_user_roles: the `extra-user-roles` for the user
            group: the consumer group

        Raises:
            `(subprocess.CalledProcessError | ops.pebble.ExecError)`: if the error returned a non-zero exit code
        """
        if "producer" in extra_user_roles:
            self.new_user_acls.update(self._generate_producer_acls(topic=topic, username=username))
        if "consumer" in extra_user_roles:
            self.new_user_acls.update(
                self._generate_consumer_acls(topic=topic, username=username, group=group)
            )

        # getting subset of all cluster ACLs for only the provided user
        current_user_acls = {acl for acl in self.current_acls if acl.username == username}

        acls_to_add = self.new_user_acls - current_user_acls
        for acl in acls_to_add:
            self.add_acl(**asdict(acl))

        acls_to_remove = current_user_acls - self.new_user_acls
        for acl in acls_to_remove:
            self.remove_acl(**asdict(acl))
