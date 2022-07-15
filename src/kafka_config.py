#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka configuration."""

import logging
from typing import Dict, Optional

from charms.kafka.v0.kafka_snap import SNAP_CONFIG_PATH, KafkaSnap, safe_write_to_file
from ops.charm import CharmBase

logger = logging.getLogger(__name__)

CHARM_KEY = "kafka"
PEER = "cluster"
REL_NAME = "zookeeper"

KAFKA_AUTH_CONFIG_PATH = f"{SNAP_CONFIG_PATH}/kafka-jaas.cfg"
OPTS = [f"-Djava.security.auth.login.config={KAFKA_AUTH_CONFIG_PATH}"]


class KafkaConfig:
    """Manager for handling Kafka configuration."""

    def __init__(self, charm: CharmBase):
        self.charm = charm

    @property
    def sync_password(self) -> Optional[str]:
        """Returns charm-set sync_password for server-server auth between brokers."""
        return self.charm.model.get_relation(PEER).data[self.charm.app].get("sync_password", None)

    @property
    def zookeeper_config(self) -> Dict[str, str]:
        """Checks the zookeeper relations for data necessary to connect to ZooKeeper.

        Returns:
            Dict with zookeeper username, password, endpoints, chroot and uris
        """
        zookeeper_config = {}
        for relation in self.charm.model.relations[REL_NAME]:
            zk_keys = ["username", "password", "endpoints", "chroot", "uris"]
            missing_config = any(
                relation.data[relation.app].get(key, None) is None for key in zk_keys
            )

            if missing_config:
                continue

            zookeeper_config.update(relation.data[relation.app])
            break

        if zookeeper_config:
            zookeeper_config["connect"] = (
                zookeeper_config["uris"].replace(zookeeper_config["chroot"], "")
                + zookeeper_config["chroot"]
            )
        return zookeeper_config

    def set_jaas_config(self) -> None:
        """Sets the Kafka JAAS config using zookeeper relation data."""
        jaas_config = f"""
            Client {{
                org.apache.zookeeper.server.auth.DigestLoginModule required
                username="{self.zookeeper_config['username']}"
                password="{self.zookeeper_config['password']}";
            }};
        """
        safe_write_to_file(content=jaas_config, path=KAFKA_AUTH_CONFIG_PATH, mode="w")

    @staticmethod
    def set_kafka_opts() -> None:
        """Sets the env-vars needed for SASL auth to /etc/environment on the unit."""
        opts_string = " ".join(OPTS)
        safe_write_to_file(content=f"KAFKA_OPTS={opts_string}", path="/etc/environment", mode="a")

    def set_server_properties(self) -> None:
        """Sets all kafka config properties to the server.properties path."""
        base_config = self.charm.config["server-properties"]
        broker_id = self.charm.unit.name.split("/")[1]
        host = (
            self.charm.model.get_relation(PEER).data[self.charm.unit].get("private-address", None)
        )
        properties = (
            f"{base_config}\n"
            f"broker.id={broker_id}\n"
            f"advertised.listeners=SASL_PLAINTEXT://{host}:9092\n"
            f'zookeeper.connect={self.zookeeper_config["connect"]}\n'
            f'listener.name.sasl_plaintext.scram-sha-512.sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="sync" password="{self.sync_password}";'
        )

        safe_write_to_file(
            content=properties, path=f"{SNAP_CONFIG_PATH}/server.properties", mode="w"
        )

    def add_user_to_zookeeper(self, username: str, password: str) -> None:
        """Adds user credentials to ZooKeeper for authorising clients and brokers.

        Raises:
            subprocess.CalledProcessError: If the command failed
        """
        command = [
            f"--zookeeper={self.zookeeper_config['connect']}",
            "--alter",
            "--entity-type=users",
            f"--entity-name={username}",
            f"--add-config=SCRAM-SHA-512=[password={password}]",
        ]
        KafkaSnap.run_bin_command(bin_keyword="configs", bin_args=command, opts=OPTS)

    def delete_user_from_zookeeper(self, username: str) -> None:
        """Deletes user credentials from ZooKeeper for authorising clients and brokers.

        Raises:
            subprocess.CalledProcessError: If the command failed
        """
        command = [
            f"--zookeeper={self.zookeeper_config['connect']}",
            "--alter",
            "--entity-type=users",
            f"--entity-name={username}",
            "--delete-config=SCRAM-SHA-512",
        ]
        KafkaSnap.run_bin_command(bin_keyword="configs", bin_args=command, opts=OPTS)
