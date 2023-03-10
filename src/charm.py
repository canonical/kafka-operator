#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed Machine Operator for Apache Kafka."""

import logging
import subprocess
from typing import MutableMapping, Optional

from charms.data_platform_libs.v0.data_models import TypedCharmBase
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.rolling_ops.v0.rollingops import RollingOpsManager, RunWithLock
from ops.charm import (
    ActionEvent,
    RelationChangedEvent,
    RelationEvent,
    RelationJoinedEvent,
    StorageAttachedEvent,
    StorageDetachingEvent,
    StorageEvent,
)
from ops.framework import EventBase
from ops.main import main
from ops.model import ActiveStatus, Relation

from auth import KafkaAuth
from config import KafkaConfig
from literals import (
    ADMIN_USER,
    CHARM_KEY,
    INTERNAL_USERS,
    PEER,
    REL_NAME,
    SNAP_NAME,
    STATUS,
    ZK,
    AvailableStatuses,
)
from provider import KafkaProvider
from snap import KafkaSnap
from structured_config import CharmConfig
from tls import KafkaTLS
from utils import broker_active, generate_password, safe_get_file

logger = logging.getLogger(__name__)


class KafkaCharm(TypedCharmBase[CharmConfig]):
    """Charmed Operator for Kafka."""

    config_type = CharmConfig

    def __init__(self, *args):
        super().__init__(*args)
        self.name = CHARM_KEY
        self.snap = KafkaSnap()
        self.kafka_config = KafkaConfig(self)
        self.tls = KafkaTLS(self)
        self.provider = KafkaProvider(self)
        self.restart = RollingOpsManager(self, relation="restart", callback=self._restart)
        self.grafana_dashboards = GrafanaDashboardProvider(self)
        self.metrics_endpoint = MetricsEndpointProvider(
            self,
            refresh_event=self.on.start,
            jobs=[{"static_configs": [{"targets": ["*:9100", "*:9101"]}]}],
        )

        self.framework.observe(getattr(self.on, "start"), self._on_start)
        self.framework.observe(getattr(self.on, "install"), self._on_install)
        self.framework.observe(getattr(self.on, "config_changed"), self._on_config_changed)
        self.framework.observe(getattr(self.on, "update_status"), self._on_update_status)

        self.framework.observe(self.on[PEER].relation_changed, self._on_config_changed)

        self.framework.observe(self.on[ZK].relation_joined, self._on_zookeeper_joined)
        self.framework.observe(self.on[ZK].relation_changed, self._on_zookeeper_changed)
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
        return self.unit_peer_data.get("private-address", "")

    @property
    def ready_to_start(self) -> bool:
        """Check for active ZooKeeper relation and adding of inter-broker auth username.

        Returns:
            True if ZK is related and `sync` user has been added. False otherwise.
        """
        if not self.peer_relation:
            self._set_status("NO_PEER_RELATION")
            return False

        if not self.kafka_config.zookeeper_related:
            self._set_status("ZK_NOT_RELATED")
            return False

        if not self.kafka_config.zookeeper_connected:
            self._set_status("ZK_NOT_CONNECTED")
            return False

        if not self.kafka_config.internal_user_credentials:
            self._set_status("NO_BROKER_CREDS")
            return False

        # TLS must be enabled for Kafka and ZK or disabled for both
        if self.tls.enabled ^ (
            self.kafka_config.zookeeper_config.get("tls", "disabled") == "enabled"
        ):
            self._set_status("ZK_TLS_MISMATCH")
            return False

        return True

    @property
    def healthy(self) -> bool:
        """Checks and updates various charm lifecycle states.

        Returns:
            True if service is alive and active. Otherwise False
        """
        if not self.ready_to_start:
            return False

        if not self.snap.active:
            self._set_status("SNAP_NOT_RUNNING")
            return False

        if not broker_active(
            unit=self.unit,
            zookeeper_config=self.kafka_config.zookeeper_config,
        ):
            self._set_status("ZK_NOT_CONNECTED")
            return False

        return True

    def _on_update_status(self, _: EventBase) -> None:
        """Handler for `update-status` events."""
        if not self.healthy:
            return

        self._set_status("ACTIVE")

    def _on_storage_attached(self, event: StorageAttachedEvent) -> None:
        """Handler for `storage_attached` events."""
        # new dirs won't be used until topic partitions are assigned to it
        # either automatically for new topics, or manually for existing
        # set status only for running services, not on startup
        if self.snap.active:
            self._set_status("ADDED_STORAGE")

        self._on_config_changed(event)

    def _on_storage_detaching(self, event: StorageDetachingEvent) -> None:
        """Handler for `storage_detaching` events."""
        # in the case where there may be replication recovery may be possible
        if self.peer_relation and len(self.peer_relation.units):
            self._set_status("REMOVED_STORAGE")
        else:
            self._set_status("REMOVED_STORAGE_NO_REPL")

        self._on_config_changed(event)

    def _on_install(self, _) -> None:
        """Handler for `install` event."""
        if self.snap.install():
            self.kafka_config.set_kafka_opts()
            self._set_status("ZK_NOT_RELATED")
        else:
            self._set_status("SNAP_NOT_INSTALLED")

    def _on_zookeeper_joined(self, event: RelationJoinedEvent) -> None:
        """Handler for `zookeeper_relation_joined` event, ensuring chroot gets set."""
        if self.unit.is_leader():
            event.relation.data[self.app].update({"chroot": "/" + self.app.name})

        self._set_status("ZK_NO_DATA")

    def _on_zookeeper_changed(self, event: RelationChangedEvent) -> None:
        """Handler for `zookeeper_relation_changed` event, ensuring internal users get created."""
        if not self.kafka_config.zookeeper_connected:
            self._set_status("ZK_NO_DATA")
            return

        # TLS must be enabled for Kafka and ZK or disabled for both
        if self.tls.enabled ^ (
            self.kafka_config.zookeeper_config.get("tls", "disabled") == "enabled"
        ):
            self._set_status("ZK_TLS_MISMATCH")
            return

        if not self.kafka_config.internal_user_credentials and self.unit.is_leader():
            try:
                internal_user_credentials = self._create_internal_credentials()
            except (KeyError, RuntimeError, subprocess.CalledProcessError):
                event.defer()
                return

            # only set to relation data when all set
            for username, password in internal_user_credentials:
                self.set_secret(scope="app", key=f"{username}-password", value=password)

        self._on_config_changed(event)

    def _on_zookeeper_broken(self, _: RelationEvent) -> None:
        """Handler for `zookeeper_relation_broken` event, ensuring charm blocks."""
        self.snap.stop_snap_service(snap_service=SNAP_NAME)

        logger.info(f'Broker {self.unit.name.split("/")[1]} disconnected')
        self._set_status("ZK_NOT_RELATED")

    def _on_start(self, event: EventBase) -> None:
        """Handler for `start` event."""
        if not self.ready_to_start:
            event.defer()
            return

        # required settings given zookeeper connection config has been created
        self.kafka_config.set_zk_jaas_config()
        self.kafka_config.set_server_properties()
        self.kafka_config.set_client_properties()

        # start kafka service
        self.snap.start_snap_service(snap_service=SNAP_NAME)

        # check for connection
        self._on_update_status(event)

        # only log once on successful 'on-start' run
        if not isinstance(self.unit.status, ActiveStatus):
            logger.info(f'Broker {self.unit.name.split("/")[1]} connected')

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
        # only attempt restart if service is already active
        if not self.healthy:
            event.defer()
            return

        self.snap.restart_snap_service(snap_service=SNAP_NAME)

        if self.healthy:
            logger.info(f'Broker {self.unit.name.split("/")[1]} restarted')
        else:
            logger.error(f"Broker {self.unit.name.split('/')[1]} failed to restart")

    # FIXME: come back here
    def _disable_enable_restart(self, event: RunWithLock) -> None:
        """Handler for `rolling_ops` disable_enable restart events."""
        if not self.healthy:
            logger.warning(f"Broker {self.unit.name.split('/')[1]} is not ready restart")
            event.defer()
            return

        self.snap.disable_enable(snap_service=SNAP_NAME)

        if isinstance(self.unit.status, ActiveStatus):
            logger.info(f'Broker {self.unit.name.split("/")[1]} restarted')
        else:
            logger.error(f"Broker {self.unit.name.split('/')[1]} failed to restart")
            return

    def _set_password_action(self, event: ActionEvent) -> None:
        """Handler for set-password action.

        Set the password for a specific user, if no passwords are passed, generate them.
        """
        if not self.healthy:
            event.defer()
            return

        username = event.params["username"]
        new_password = event.params.get("password", generate_password())

        if new_password in self.kafka_config.internal_user_credentials.values():
            msg = "Password already exists, please choose a different password."
            logger.error(msg)
            event.fail(msg)
            return

        try:
            self._update_internal_user(username=username, password=new_password)
        except Exception as e:
            logger.error(str(e))
            event.fail(f"unable to set password for {username}")

        # Store the password on application databag
        self.set_secret(scope="app", key=f"{username}-password", value=new_password)
        event.set_results({f"{username}-password": new_password})

    def _get_admin_credentials_action(self, event: ActionEvent) -> None:
        client_properties = safe_get_file(self.kafka_config.client_properties_filepath)

        if not client_properties:
            msg = "client.properties file not found on target unit."
            logger.error(msg)
            event.fail(msg)
            return

        admin_properties = set(client_properties) - set(self.kafka_config.tls_properties)

        event.set_results(
            {
                "username": ADMIN_USER,
                "password": self.kafka_config.internal_user_credentials[ADMIN_USER],
                "client-properties": "\n".join(admin_properties),
            }
        )

    def _update_internal_user(self, username: str, password: str) -> None:
        """Updates internal SCRAM usernames and passwords.

        Raises:
            RuntimeError if called from non-leader unit
            KeyError if attempted to update non-leader unit
            subprocess.CalledProcessError if command to ZooKeeper failed
        """
        if not self.unit.is_leader():
            raise RuntimeError("Cannot update internal user from non-leader unit.")

        if username not in INTERNAL_USERS:
            raise KeyError(
                f"Can only update internal charm users: {INTERNAL_USERS}, not {username}."
            )

        # do not start units until SCRAM users have been added to ZooKeeper for server-server auth
        kafka_auth = KafkaAuth(
            self,
            opts=self.kafka_config.extra_args,
            zookeeper=self.kafka_config.zookeeper_config.get("connect", ""),
        )

        kafka_auth.add_user(
            username=username,
            password=password,
        )

    def _create_internal_credentials(self) -> list[tuple[str, str]]:
        """Creates internal SCRAM users during cluster start.

        Returns:
            List of (username, password) for all internal users


        Raises:
            RuntimeError if called from non-leader unit
            KeyError if attempted to update non-leader unit
            subprocess.CalledProcessError if command to ZooKeeper failed
        """
        credentials = [(username, generate_password()) for username in INTERNAL_USERS]
        for username, password in credentials:
            password = generate_password()
            self._update_internal_user(username=username, password=password)

        return credentials

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

    def _set_status(self, key: AvailableStatuses) -> None:
        """Sets charm status."""
        self.unit.status = STATUS[key]


if __name__ == "__main__":
    main(KafkaCharm)
