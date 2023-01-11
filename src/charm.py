#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed Machine Operator for Apache Kafka."""

import logging
import subprocess
from typing import MutableMapping, Optional

from auth import KafkaAuth
from charms.rolling_ops.v0.rollingops import RollingOpsManager
from config import KafkaConfig
from literals import ADMIN_USER, CHARM_KEY, INTER_BROKER_USER, PEER, REL_NAME, ZK
from ops.charm import (
    ActionEvent,
    CharmBase,
    LeaderElectedEvent,
    RelationEvent,
    RelationJoinedEvent,
    StorageAttachedEvent,
    StorageDetachingEvent,
    StorageEvent,
)
from ops.framework import EventBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, Relation, WaitingStatus
from provider import KafkaProvider
from snap import KafkaSnap
from tls import KafkaTLS
from utils import broker_active, generate_password, safe_get_file

logger = logging.getLogger(__name__)


class KafkaCharm(CharmBase):
    """Charmed Operator for Kafka."""

    def __init__(self, *args):
        super().__init__(*args)
        self.name = CHARM_KEY
        self.snap = KafkaSnap()
        self.kafka_config = KafkaConfig(self)
        self.tls = KafkaTLS(self)
        self.provider = KafkaProvider(self)
        self.restart = RollingOpsManager(self, relation="restart", callback=self._restart)

        self.framework.observe(getattr(self.on, "start"), self._on_start)
        self.framework.observe(getattr(self.on, "install"), self._on_install)
        self.framework.observe(getattr(self.on, "leader_elected"), self._on_leader_elected)
        self.framework.observe(getattr(self.on, "config_changed"), self._on_config_changed)

        self.framework.observe(self.on[PEER].relation_changed, self._on_config_changed)

        self.framework.observe(self.on[ZK].relation_joined, self._on_zookeeper_joined)
        self.framework.observe(self.on[ZK].relation_changed, self._on_config_changed)
        self.framework.observe(self.on[ZK].relation_broken, self._on_zookeeper_broken)

        self.framework.observe(getattr(self.on, "set_password_action"), self._set_password_action)
        self.framework.observe(getattr(self.on, "rolling_restart_unit_action"), self._restart)
        self.framework.observe(
            getattr(self.on, "get_admin_credentials_action"), self._get_admin_credentials_action
        )

        self.framework.observe(
            getattr(self.on, "log_data_storage_attached"), self._on_storage_attached
        )
        self.framework.observe(
            getattr(self.on, "log_data_storage_detaching"), self._on_storage_detaching
        )

    @property
    def peer_relation(self) -> Optional[Relation]:
        """The cluster peer relation."""
        return self.model.get_relation(PEER)

    @property
    def app_peer_data(self) -> MutableMapping[str, str]:
        """Application peer relation data object."""
        if not self.peer_relation:
            return {}

        return self.peer_relation.data[self.app]

    @property
    def unit_peer_data(self) -> MutableMapping[str, str]:
        """Unit peer relation data object."""
        if not self.peer_relation:
            return {}

        return self.peer_relation.data[self.unit]

    @property
    def unit_host(self) -> str:
        """Return the own host."""
        return self.unit_peer_data.get("private-address", None)

    def _on_storage_attached(self, event: StorageAttachedEvent) -> None:
        """Handler for `storage_attached` events."""
        # checks first whether the broker is active before warning
        if not self.kafka_config.zookeeper_connected or not broker_active(
            unit=self.unit, zookeeper_config=self.kafka_config.zookeeper_config
        ):
            return

        # new dirs won't be used until topic partitions are assigned to it
        # either automatically for new topics, or manually for existing
        message = (
            "manual partition reassignment may be needed for Kafka to utilize new storage volumes"
        )
        logger.warning(f"attaching storage - {message}")
        self.unit.status = ActiveStatus(message)

        self._on_config_changed(event)

    def _on_storage_detaching(self, event: StorageDetachingEvent) -> None:
        """Handler for `storage_detaching` events."""
        # checks first whether the broker is active before warning
        if not self.kafka_config.zookeeper_connected or not broker_active(
            unit=self.unit, zookeeper_config=self.kafka_config.zookeeper_config
        ):
            return

        # in the case where there may be replication recovery may be possible
        if self.peer_relation and len(self.peer_relation.units):
            message = "manual partition reassignment from replicated brokers recommended due to lost partitions on removed storage volumes"
            logger.warning(f"removing storage - {message}")
            self.unit.status = BlockedStatus(message)
        else:
            message = "potential log-data loss due to storage removal without replication"
            logger.error(f"removing storage - {message}")
            self.unit.status = BlockedStatus(message)

        self._on_config_changed(event)

    def _on_install(self, _) -> None:
        """Handler for `install` event."""
        if self.snap.install():
            self.kafka_config.set_kafka_opts()
            self.unit.status = WaitingStatus("waiting for zookeeper relation")
        else:
            self.unit.status = BlockedStatus("unable to install kafka snap")

    def _on_leader_elected(self, event: LeaderElectedEvent) -> None:
        """Handler for `leader_elected` event, ensuring internal user passwords get set."""
        if not self.peer_relation:
            logger.debug("no peer relation")
            event.defer()
            return

        self.set_internal_passwords()

    def _on_zookeeper_joined(self, event: RelationJoinedEvent) -> None:
        """Handler for `zookeeper_relation_joined` event, ensuring chroot gets set."""
        if self.unit.is_leader():
            event.relation.data[self.app].update({"chroot": "/" + self.app.name})

    def _on_zookeeper_broken(self, _: RelationEvent) -> None:
        """Handler for `zookeeper_relation_broken` event, ensuring charm blocks."""
        self.snap.stop_snap_service(snap_service=CHARM_KEY)
        logger.info(f'Broker {self.unit.name.split("/")[1]} disconnected')
        self.unit.status = BlockedStatus("missing required zookeeper relation")

    def _on_start(self, event: EventBase) -> None:
        """Handler for `start` event."""
        if not self.kafka_config.zookeeper_connected:
            event.defer()
            return

        if not self.peer_relation:
            logger.debug("no peer relation")
            event.defer()
            return

        # required settings given zookeeper connection config has been created
        self.kafka_config.set_zk_jaas_config()
        self.kafka_config.set_server_properties()
        self.kafka_config.set_client_properties()

        # set internal passwords
        if self.unit.is_leader():
            for username, password in self.kafka_config.internal_user_credentials.items():
                updated_user = self.update_internal_user(username=username, password=password)
                # do not continue until both internal users are updated
                if not updated_user:
                    event.defer()
                    return

            # updating non-leader units of creation of internal users
            self.peer_relation.data[self.app].update({"broker-creds": "added"})

        # for non-leader units
        if not self.ready_to_start:
            event.defer()
            return

        # start kafka service
        start_snap = self.snap.start_snap_service(snap_service=CHARM_KEY)
        if not start_snap:
            self.unit.status = BlockedStatus("unable to start snap")
            return

        # start_snap_service can fail silently, confirm with ZK if kafka is actually connected
        if broker_active(
            unit=self.unit,
            zookeeper_config=self.kafka_config.zookeeper_config,
        ):
            logger.info(f'Broker {self.unit.name.split("/")[1]} connected')
            self.unit.status = ActiveStatus()
        else:
            self.unit.status = BlockedStatus("kafka unit not connected to ZooKeeper")
            return

    def _on_config_changed(self, event: EventBase) -> None:
        """Generic handler for most `config_changed` events across relations."""
        if not self.ready_to_start:
            event.defer()
            return

        # Load current properties set in the charm workload
        properties = safe_get_file(self.kafka_config.server_properties_filepath)
        if not properties:
            # Event fired before charm has properly started
            event.defer()
            return

        if set(properties) ^ set(self.kafka_config.server_properties):
            logger.info(
                (
                    f'Broker {self.unit.name.split("/")[1]} updating config - '
                    f"OLD PROPERTIES = {set(properties) - set(self.kafka_config.server_properties)}, "
                    f"NEW PROPERTIES = {set(self.kafka_config.server_properties) - set(properties)}"
                )
            )
            self.kafka_config.set_server_properties()
            self.kafka_config.set_client_properties()

            if isinstance(event, StorageEvent):  # to get new storages
                self.on[f"{self.restart.name}"].acquire_lock.emit(
                    callback_override="_disable_enable_restart"
                )
            else:
                self.on[f"{self.restart.name}"].acquire_lock.emit()

        # If Kafka is related to client charms, update their information.
        if self.model.relations.get(REL_NAME, None) and self.unit.is_leader():
            self.provider.update_connection_info()

    def _restart(self, event: EventBase) -> None:
        """Handler for `rolling_ops` restart events."""
        if not self.ready_to_start:
            event.defer()
            return

        self.snap.restart_snap_service("kafka")

        if broker_active(
            unit=self.unit,
            zookeeper_config=self.kafka_config.zookeeper_config,
        ):
            logger.info(f'Broker {self.unit.name.split("/")[1]} restarted')
            self.unit.status = ActiveStatus()
        else:
            self.unit.status = BlockedStatus(
                f"Broker {self.unit.name.split('/')[1]} failed to restart"
            )
            return

    def _disable_enable_restart(self, event: ActionEvent) -> None:
        """Handler for `rolling_ops` disable_enable restart events."""
        if not self.ready_to_start:
            event.fail(message=f"Broker {self.unit.name.split('/')[1]} is not ready restart")
            return

        self.snap.disable_enable("kafka")

        if broker_active(
            unit=self.unit,
            zookeeper_config=self.kafka_config.zookeeper_config,
        ):
            logger.info(f'Broker {self.unit.name.split("/")[1]} restarted')
            self.unit.status = ActiveStatus()
        else:
            msg = f"Broker {self.unit.name.split('/')[1]} failed to restart"
            event.fail(message=msg)
            self.unit.status = BlockedStatus(msg)
            return

    def _set_password_action(self, event: ActionEvent) -> None:
        """Handler for set-password action.

        Set the password for a specific user, if no passwords are passed, generate them.
        """
        if not self.peer_relation:
            logger.debug("no peer relation")
            event.defer()
            return

        if not self.unit.is_leader():
            msg = "Password rotation must be called on leader unit"
            logger.error(msg)
            event.fail(msg)
            return

        username = event.params.get("username", "")
        new_password = event.params.get("password", generate_password())

        if new_password in self.kafka_config.internal_user_credentials.values():
            msg = "Password already exists, please choose a different password."
            logger.error(msg)
            event.fail(msg)
            return

        user_updated = self.update_internal_user(username=username, password=new_password)
        if not user_updated:
            event.fail("Unable to update user.")
            return

        # Store the password on application databag
        self.set_secret(scope="app", key=f"{username}-password", value=new_password)
        event.set_results({f"{username}-password": new_password})

    @property
    def ready_to_start(self) -> bool:
        """Check for active ZooKeeper relation and adding of inter-broker auth username.

        Returns:
            True if ZK is related and `sync` user has been added. False otherwise.
        """
        if not self.peer_relation:
            logger.debug("no peer relation")
            return False

        # TLS must be enabled for Kafka and ZK or disabled for both
        if self.tls.enabled ^ (
            self.kafka_config.zookeeper_config.get("tls", "disabled") == "enabled"
        ):
            msg = "TLS must be enabled for Zookeeper and Kafka"
            logger.error(msg)
            self.unit.status = BlockedStatus(msg)
            return False

        storage_metadata = self.meta.storages["log-data"]
        min_storages = storage_metadata.multiple_range[0] if storage_metadata.multiple_range else 0
        if len(self.model.storages["log-data"]) < min_storages:
            msg = f"Storage volumes lower than minimum of {min_storages}"
            logger.error(msg)
            self.unit.status = BlockedStatus(msg)
            return False

        if not self.kafka_config.zookeeper_connected or not self.peer_relation.data[self.app].get(
            "broker-creds", None
        ):
            return False

        return True

    def _get_admin_credentials_action(self, event: ActionEvent) -> None:
        client_properties = safe_get_file(self.kafka_config.client_properties_filepath)

        if not client_properties:
            msg = "client.properties file not found on target unit."
            logger.error(msg)
            event.fail(msg)
            return

        event.set_results(
            {
                "username": ADMIN_USER,
                "password": self.kafka_config.internal_user_credentials[ADMIN_USER],
                "client-properties": "\n".join(client_properties),
            }
        )

    def update_internal_user(self, username: str, password: str) -> bool:
        """Updates internal SCRAM usernames and passwords."""
        if not self.unit.is_leader():
            logger.debug("Cannot update internal user from non-leader unit.")
            return False

        if username not in [INTER_BROKER_USER, ADMIN_USER]:
            msg = f"Can only update internal charm users: {INTER_BROKER_USER} or {ADMIN_USER}, not {username}."
            logger.error(msg)
            return False

        # do not start units until SCRAM users have been added to ZooKeeper for server-server auth
        kafka_auth = KafkaAuth(
            self,
            opts=self.kafka_config.extra_args,
            zookeeper=self.kafka_config.zookeeper_config.get("connect", ""),
        )
        try:
            kafka_auth.add_user(
                username=username,
                password=password,
            )
            return True

        except subprocess.CalledProcessError as e:
            # command to add users fails if attempted too early
            logger.debug(str(e))
            return False

    def set_internal_passwords(self) -> None:
        """Sets inter-broker and admin user passwords to app relation data."""
        if not self.unit.is_leader():
            return

        for password in [f"{INTER_BROKER_USER}-password", f"{ADMIN_USER}-password"]:
            current_password = self.get_secret(scope="app", key=password)
            self.set_secret(
                scope="app", key=password, value=(current_password or generate_password())
            )

    def get_secret(self, scope: str, key: str) -> Optional[str]:
        """Get TLS secret from the secret storage.

        Args:
            scope: whether this secret is for a `unit` or `app`
            key: the secret key name

        Returns:
            String of key value.
            None if non-existent key
        """
        if scope == "unit":
            return self.unit_peer_data.get(key, None)
        elif scope == "app":
            return self.app_peer_data.get(key, None)
        else:
            raise RuntimeError("Unknown secret scope.")

    def set_secret(self, scope: str, key: str, value: Optional[str]) -> None:
        """Get TLS secret from the secret storage.

        Args:
            scope: whether this secret is for a `unit` or `app`
            key: the secret key name
            value: the value for the secret key
        """
        if scope == "unit":
            if not value:
                self.unit_peer_data.update({key: ""})
                return
            self.unit_peer_data.update({key: value})
        elif scope == "app":
            if not value:
                self.app_peer_data.update({key: ""})
                return
            self.app_peer_data.update({key: value})
        else:
            raise RuntimeError("Unknown secret scope.")


if __name__ == "__main__":
    main(KafkaCharm)
