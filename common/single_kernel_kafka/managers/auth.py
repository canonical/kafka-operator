#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Supporting objects for Kafka user and ACL management."""

import logging
import re
import subprocess  # nosec B404
from dataclasses import asdict, dataclass

from ops.pebble import ExecError

from ..core.cluster import KafkaContext
from ..core.connect_models import ConnectContext
from ..core.literals import GROUP, USER_NAME
from ..core.models import KafkaPermissionModel
from ..core.workload import WorkloadBase

logger = logging.getLogger(__name__)

CLUSTER_RESOURCE_NAME = "kafka-cluster"
# Kafka resource types (as reported by `kafka-acls --list`) mapped to their CLI flag
RESOURCE_TYPE_FLAGS = {
    "TOPIC": "topic",
    "GROUP": "group",
    "TRANSACTIONAL_ID": "transactional-id",
}


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
        self, state: KafkaContext, workload: WorkloadBase, kafka_opts: str, log4j_opts: str
    ):
        self.state = state
        self.workload = workload
        self.kafka_opts = kafka_opts
        self.log4j_opts = log4j_opts

    @property
    def current_acls(self) -> set[Acl]:
        """Sets the current cluster ACLs."""
        acls = self._get_acls_from_cluster()
        return self._parse_acls(acls=acls)

    def _get_acls_from_cluster(self) -> str:
        """Loads the currently active ACLs from the Kafka cluster."""
        command = [
            f"--bootstrap-server={self.state.bootstrap_server_internal}",
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
    def _parse_describe_users(raw: str) -> list[str]:
        """Parses the configs --describe command for entity-type=users and returns a list of users."""
        return re.findall(r"user-principal '([^']+)'", raw)

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

    @staticmethod
    def _generate_manager_acls(username: str) -> set[Acl]:
        """Generates expected set of `Acl`s for a `manager` client application, e.g Kafka UI."""
        manager_acls = set()
        for resource_type in ("TOPIC", "GROUP", "TRANSACTIONAL_ID"):
            manager_acls.add(
                Acl(
                    resource_type=resource_type,
                    resource_name="*",
                    username=username,
                    operation="ALL",
                )
            )

        for operation in ("DESCRIBE", "DESCRIBE_CONFIGS"):
            manager_acls.add(
                Acl(
                    resource_type="CLUSTER",
                    resource_name=CLUSTER_RESOURCE_NAME,
                    username=username,
                    operation=operation,
                )
            )

        return manager_acls

    @staticmethod
    def _acl_args(operation: str, resource_type: str, resource_name: str) -> list[str]:
        """Builds the `kafka-acls` CLI args for a given operation and resource.

        Args:
            operation: the ACL operation as reported by Kafka, e.g `READ`, `DESCRIBE_CONFIGS`
            resource_type: the resource type as reported by Kafka,
                e.g `TOPIC`, `GROUP`, `TRANSACTIONAL_ID`, `CLUSTER`
            resource_name: the name of the resource

        Raises:
            ValueError: if the resource type is not supported
        """
        # CLI expects PascalCase operations, e.g DESCRIBE_CONFIGS -> DescribeConfigs
        cli_operation = "".join(part.capitalize() for part in operation.split("_"))
        args = [f"--operation={cli_operation}"]

        if resource_type == "CLUSTER":
            return args + ["--cluster"]

        if resource_type not in RESOURCE_TYPE_FLAGS:
            raise ValueError(f"Unsupported ACL resource type: {resource_type}")

        if resource_name == "*":
            # wildcard resource, only valid with LITERAL pattern
            pattern = "LITERAL"
        elif resource_type == "GROUP":
            pattern = "PREFIXED"
        elif len(resource_name) > 3 and resource_name.endswith("*"):
            pattern = "PREFIXED"
            resource_name = resource_name[:-1]
        else:
            pattern = "LITERAL"

        return args + [
            f"--{RESOURCE_TYPE_FLAGS[resource_type]}={resource_name}",
            f"--resource-pattern-type={pattern}",
        ]

    def add_user(self, username: str, password: str) -> None:
        """Adds new user credentials to cluster.

        Args:
            username: the user name to add
            password: the user password

        Raises:
            `(subprocess.CalledProcessError | ops.pebble.ExecError)`: if the error returned a non-zero exit code
        """
        command = [
            "--alter",
            "--entity-type=users",
            f"--entity-name={username}",
            f"--add-config=SCRAM-SHA-512=[password={password}]",
            f"--bootstrap-server={self.state.bootstrap_server_internal}",
            f"--command-config={self.workload.paths.client_properties}",
        ]

        self.workload.run_bin_command(
            bin_keyword="configs", bin_args=command, opts=[self.log4j_opts]
        )

    def delete_user(self, username: str) -> None:
        """Deletes user credentials from cluster.

        Args:
            username: the user name to delete

        Raises:
            `(subprocess.CalledProcessError | ops.pebble.ExecError)`: if the error returned a non-zero exit code
        """
        command = [
            f"--bootstrap-server={self.state.bootstrap_server_internal}",
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
            if "delete a user credential that does not exist" in f"{e.stdout} {e.stderr}":
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
                e.g `READ`, `WRITE`, `DESCRIBE`, `ALL`
            resource_type: the resource type to grant ACLs for
                e.g `GROUP`, `TOPIC`, `TRANSACTIONAL_ID`, `CLUSTER`
            resource_name: the name of the resource to grant ACLs for

        Raises:
            `(subprocess.CalledProcessError | ops.pebble.ExecError)`: if the error returned a non-zero exit code
        """
        command = [
            f"--bootstrap-server={self.state.bootstrap_server_internal}",
            f"--command-config={self.workload.paths.client_properties}",
            "--add",
            f"--allow-principal=User:{username}",
        ] + self._acl_args(operation, resource_type, resource_name)

        logger.info(f"CREATE ACL - {command}")
        self.workload.run_bin_command(bin_keyword="acls", bin_args=command, opts=[self.log4j_opts])

    def remove_acl(
        self, username: str, operation: str, resource_type: str, resource_name: str
    ) -> None:
        """Removes ACL rule for the cluster.

        Args:
            username: the user name to remove ACLs for
            operation: the operation to remove
                e.g `READ`, `WRITE`, `DESCRIBE`, `ALL`
            resource_type: the resource type to remove ACLs for
                e.g `GROUP`, `TOPIC`, `TRANSACTIONAL_ID`, `CLUSTER`
            resource_name: the name of the resource to remove ACLs for

        Raises:
            `(subprocess.CalledProcessError | ops.pebble.ExecError)`: if the error returned a non-zero exit code
        """
        command = [
            f"--bootstrap-server={self.state.bootstrap_server_internal}",
            f"--command-config={self.workload.paths.client_properties}",
            "--remove",
            f"--allow-principal=User:{username}",
            "--force",
        ] + self._acl_args(operation, resource_type, resource_name)

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
        self,
        username: str,
        topic: str,
        extra_user_roles: str,
        group: str | None,
        permissions: list[KafkaPermissionModel],
    ) -> None:
        """Compares data passed from the client relation, and updating cluster ACLs to match.

        `producer`s are granted READ, DESCRIBE and WRITE access for a given topic
        `consumer`s are granted READ, DESCRIBE access for a given topic, and READ access for a
            generated consumer group
        `manager`s are granted ALL access on every topic, group and transactional ID, and
            DESCRIBE, DESCRIBE_CONFIGS access on the cluster

        If new ACLs provided do not match existing ACLs set for the cluster, existing ACLs will
            be revoked

        Args:
            username: the user name to update ACLs for
            topic: the topic to update ACLs for
            extra_user_roles: the `extra-user-roles` for the user
            group: the consumer group
            permissions: list of additional permissions requested by the client

        Raises:
            `(subprocess.CalledProcessError | ops.pebble.ExecError)`: if the error returned a non-zero exit code
        """
        computed_user_acls: set[Acl] = set()
        if "producer" in extra_user_roles:
            computed_user_acls.update(self._generate_producer_acls(topic=topic, username=username))
        if "consumer" in extra_user_roles:
            computed_user_acls.update(
                self._generate_consumer_acls(topic=topic, username=username, group=group)
            )
        if "manager" in {role.strip() for role in extra_user_roles.split(",")}:
            computed_user_acls.update(self._generate_manager_acls(username=username))
        if permissions:
            for permission in permissions:
                for operation in permission.privileges:
                    computed_user_acls.add(
                        Acl(
                            resource_type=permission.resource_type,
                            resource_name=permission.resource_name,
                            username=username,
                            operation=operation,
                        )
                    )

        # getting subset of all cluster ACLs for only the provided user
        current_user_acls = {acl for acl in self.current_acls if acl.username == username}

        acls_to_add = computed_user_acls - current_user_acls
        for acl in acls_to_add:
            self.add_acl(**asdict(acl))

        acls_to_remove = current_user_acls - computed_user_acls
        for acl in acls_to_remove:
            self.remove_acl(**asdict(acl))

    def get_users(self):
        """Returns all users defined on the Apache Kafka cluster.

        Raises:
            `(subprocess.CalledProcessError | ops.pebble.ExecError)`: if the error returned a non-zero exit code
        """
        command = [
            f"--bootstrap-server={self.state.bootstrap_server_internal}",
            f"--command-config={self.workload.paths.client_properties}",
            "--describe",
            "--entity-type=users",
        ]

        output = self.workload.run_bin_command(bin_keyword="configs", bin_args=command)

        return self._parse_describe_users(output)


class ConnectAuthManager:
    """Manager for handling Kafka Connect `PropertyFileLoginModule`-style credential file stores.

    These files consist of several lines in the format `{USER}: {PASSWORD}`.
    """

    DELIMITER = ":"

    def __init__(self, context: ConnectContext, workload: WorkloadBase, store_path: str):
        self.context = context
        self.workload = workload
        self.store_path = store_path

    def _load_credentials(self) -> dict[str, str]:
        """Loads credentials from internal file store and returns a dict of username: password mappings."""
        raw = self.workload.read(self.store_path)
        credentials = {}
        for line in raw:
            parts = line.split(self.DELIMITER)
            if len(parts) == 2:
                credentials[parts[0].strip()] = parts[1].strip()

        return credentials

    def _save_credentials(self, cache: dict[str, str]) -> None:
        """Saves a map of credentials to the internal file store.

        Args:
            cache (dict[str, str]): a dict of username: password mapping to be saved to internal file store.
        """
        raw = [f"{username}{self.DELIMITER} {password}" for username, password in cache.items()]
        self.workload.write(content="\n".join(raw) + "\n", path=self.store_path)

        self.workload.exec(f"chown {USER_NAME}:{GROUP} {self.store_path}".split())
        self.workload.exec(["chmod", "770", self.store_path])

    def update(self, credentials: dict[str, str]) -> None:
        """Updates credentials in the internal file store.

        Args:
            credentials (dict[str, str]): a dict of username: password mapping to be updated.
        """
        cache = self._load_credentials() | credentials
        self._save_credentials(cache)

    def remove_user(self, username: str) -> None:
        """Removes a username from the internal file store."""
        cache = {u: p for u, p in self.credentials.items() if u != username}
        self._save_credentials(cache)

    @property
    def credentials(self) -> dict[str, str]:
        """Returns a dict mapping of username: password."""
        return self._load_credentials()
