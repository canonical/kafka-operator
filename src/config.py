#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka configuration."""

import logging
import os
from typing import Dict, List, Optional

from ops.model import Unit

from literals import PEER, REL_NAME, ZK
from snap import SNAP_CONFIG_PATH
from utils import safe_write_to_file

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_OPTIONS = """
sasl.enabled.mechanisms=SCRAM-SHA-512
sasl.mechanism.inter.broker.protocol=SCRAM-SHA-512
authorizer.class.name=kafka.security.authorizer.AclAuthorizer
allow.everyone.if.no.acl.found=false
"""


class KafkaConfig:
    """Manager for handling Kafka configuration."""

    def __init__(self, charm):
        self.charm = charm
        self.default_config_path = SNAP_CONFIG_PATH
        self.properties_filepath = f"{self.default_config_path}/server.properties"
        self.jaas_filepath = f"{self.default_config_path}/kafka-jaas.cfg"
        self.keystore_filepath = f"{self.default_config_path}/keystore.p12"
        self.truststore_filepath = f"{self.default_config_path}/truststore.jks"

    @property
    def sync_password(self) -> Optional[str]:
        """Returns charm-set sync_password for server-server auth between brokers."""
        return self.charm.get_secret(scope="app", key="sync-password")

    @property
    def zookeeper_config(self) -> Dict[str, str]:
        """The config from current ZooKeeper relations for data necessary for broker connection.

        Returns:
            Dict of ZooKeeeper:
            `username`, `password`, `endpoints`, `chroot`, `connect`, `uris` and `tls`
        """
        zookeeper_config = {}
        # loop through all relations to ZK, attempt to find all needed config
        for relation in self.charm.model.relations[ZK]:
            zk_keys = ["username", "password", "endpoints", "chroot", "uris", "tls"]
            missing_config = any(
                relation.data[relation.app].get(key, None) is None for key in zk_keys
            )

            # skip if config is missing
            if missing_config:
                continue

            # set if exists
            zookeeper_config.update(relation.data[relation.app])
            break

        if zookeeper_config:
            sorted_uris = sorted(
                zookeeper_config["uris"].replace(zookeeper_config["chroot"], "").split(",")
            )
            sorted_uris[-1] = sorted_uris[-1] + zookeeper_config["chroot"]
            zookeeper_config["connect"] = ",".join(sorted_uris)

        return zookeeper_config

    @property
    def zookeeper_connected(self) -> bool:
        """Checks if there is an active ZooKeeper relation.

        Returns:
            True if ZooKeeper is currently related with sufficient relation data
                for a broker to connect with. False otherwise.
        """
        if self.zookeeper_config.get("connect", None):
            return True

        return False

    @property
    def extra_args(self) -> List[str]:
        """The necessary Java config options for SASL/SCRAM auth.

        Returns:
            List of Java config options
        """
        return [f"-Djava.security.auth.login.config={self.jaas_filepath}"]

    @property
    def bootstrap_server(self) -> List[str]:
        """The current Kafka uris formatted for the `bootstrap-server` command flag.

        Returns:
            List of `bootstrap-server` servers
        """
        units: List[Unit] = list(
            set([self.charm.unit] + list(self.charm.model.get_relation(PEER).units))
        )
        hosts = [
            self.charm.model.get_relation(PEER).data[unit].get("private-address") for unit in units
        ]
        port = 9093 if self.charm.tls.enabled else 9092
        return [f"{host}:{port}" for host in hosts]

    @property
    def default_replication_properties(self) -> List[str]:
        """Builds replication-related properties based on the expected app size.

        Returns:
            List of properties to be set
        """
        replication_factor = min([3, self.charm.app.planned_units()])
        min_isr = max([1, replication_factor - 1])

        return [
            f"default.replication.factor={replication_factor}",
            f"num.partitions={replication_factor}",
            f"transaction.state.log.replication.factor={replication_factor}",
            f"offsets.topic.replication.factor={replication_factor}",
            f"min.insync.replicas={min_isr}",
            f"transaction.state.log.min.isr={min_isr}",
        ]

    @property
    def auth_properties(self) -> List[str]:
        """Builds properties necessary for inter-broker authorization through ZooKeeper.

        Returns:
            List of properties to be set
        """
        broker_id = self.charm.unit.name.split("/")[1]
        return [
            f"broker.id={broker_id}",
            f'zookeeper.connect={self.zookeeper_config["connect"]}',
        ]

    @property
    def tls_properties(self) -> List[str]:
        """Builds the properties necessary for TLS authentication.

        Returns:
            list of properties to be set
        """
        return [
            "zookeeper.ssl.client.enable=true",
            f"zookeeper.ssl.truststore.location={self.truststore_filepath}",
            f"zookeeper.ssl.truststore.password={self.charm.tls.truststore_password}",
            "zookeeper.clientCnxnSocket=org.apache.zookeeper.ClientCnxnSocketNetty",
            f"ssl.truststore.location={self.truststore_filepath}",
            f"ssl.truststore.password={self.charm.tls.truststore_password}",
            f"ssl.keystore.location={self.keystore_filepath}",
            f"ssl.keystore.password={self.charm.tls.keystore_password}",
            "zookeeper.ssl.endpoint.identification.algorithm=",
            "ssl.endpoint.identification.algorithm=",
            "ssl.client.auth=none",
        ]

    @property
    def super_users(self) -> str:
        """Generates all users with super/admin permissions for the cluster from relations.

        Formatting allows passing to the `super.users` property.

        Returns:
            Semicolon delimited string of current super users
        """
        super_users = ["sync"]
        for relation in self.charm.model.relations[REL_NAME]:
            extra_user_roles = relation.data[relation.app].get("extra-user-roles", "")
            password = (
                self.charm.model.get_relation(PEER)
                .data[self.charm.app]
                .get(f"relation-{relation.id}", None)
            )
            # if passwords are set for client admins, they're good to load
            if "admin" in extra_user_roles and password is not None:
                super_users.append(f"relation-{relation.id}")

        super_users_arg = [f"User:{user}" for user in super_users]

        return ";".join(super_users_arg)

    @property
    def log_dirs(self) -> List[str]:
        """Builds the necessary log.dirs based on mounted storage volumes.

        Returns:
            List of property log.dirs to be set
        """
        log_dirs = ",".join(
            [os.fspath(storage.location) for storage in self.charm.model.storages["logs"]]
        )
        return [f"log.dirs={log_dirs}"]

    @property
    def server_properties(self) -> List[str]:
        """Builds all properties necessary for starting Kafka service.

        This includes charm config, replication, SASL/SCRAM auth and default properties.

        Returns:
            List of properties to be set
        """
        host = (
            self.charm.model.get_relation(PEER).data[self.charm.unit].get("private-address", None)
        )
        port = 9093 if self.charm.tls.enabled else 9092
        protocol = "SASL_SSL" if self.charm.tls.enabled else "SASL_PLAINTEXT"

        properties = (
            [
                f"offsets.retention.minutes={self.charm.config['offsets-retention-minutes']}",
                f"log.retention.hours={self.charm.config['log-retention-hours']}",
                f"auto.create.topics={self.charm.config['auto-create-topics']}",
                f"super.users={self.super_users}",
                f"listeners={protocol}://:{port}",
                f"advertised.listeners={protocol}://{host}:{port}",
                f'listener.name.{(protocol).lower()}.scram-sha-512.sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="sync" password="{self.sync_password}";',
                f"security.inter.broker.protocol={protocol}",
                f"security.protocol={protocol}",
            ]
            + self.default_replication_properties
            + self.auth_properties
            + self.log_dirs
            + DEFAULT_CONFIG_OPTIONS.split("\n")
        )

        if self.charm.tls.enabled:
            properties += self.tls_properties

        return properties

    def set_jaas_config(self) -> None:
        """Writes the Kafka JAAS config using ZooKeeper relation data."""
        jaas_config = f"""
            Client {{
                org.apache.zookeeper.server.auth.DigestLoginModule required
                username="{self.zookeeper_config['username']}"
                password="{self.zookeeper_config['password']}";
            }};
        """
        safe_write_to_file(content=jaas_config, path=self.jaas_filepath, mode="w")

    def set_server_properties(self) -> None:
        """Writes all Kafka config properties to the `server.properties` path."""
        safe_write_to_file(
            content="\n".join(self.server_properties),
            path=self.properties_filepath,
            mode="w",
        )

    def set_kafka_opts(self) -> None:
        """Writes the env-vars needed for SASL/SCRAM auth to `/etc/environment` on the unit."""
        opts_string = " ".join(self.extra_args)
        safe_write_to_file(
            content=f"KAFKA_OPTS={opts_string}",
            path="/etc/environment",
            mode="a",
        )
