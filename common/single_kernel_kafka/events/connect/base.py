#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Event Handler for Kafka Connect related events."""

import logging
from typing import TYPE_CHECKING

from charms.data_platform_libs.v0.data_interfaces import PLUGIN_URL_NOT_REQUIRED
from ops.charm import (
    ConfigChangedEvent,
    UpdateStatusEvent,
)
from ops.framework import EventBase, Object

from ...core.literals import ConnectLiterals, ConnectStatus
from ...managers.connect import PluginDownloadFailedError
from .provider import ConnectProvider

if TYPE_CHECKING:
    from ...core.connect_models import ConnectCharmBase


logger = logging.getLogger(__name__)


class ConnectHandler(Object):
    """Handler for events related to Kafka Connect worker."""

    def __init__(self, charm: "ConnectCharmBase") -> None:
        super().__init__(charm, "connect-worker")
        self.charm: "ConnectCharmBase" = charm
        self.context = charm.context
        self.workload = charm.workload
        self.unit_tls_context = self.context.worker_unit.tls

        self.framework.observe(getattr(self.charm.on, "update_status"), self._update_status)
        self.framework.observe(getattr(self.charm.on, "config_changed"), self._on_config_changed)
        self.framework.observe(
            self.charm.on[ConnectLiterals.PEER_REL].relation_changed, self._on_config_changed
        )

        # instantiate the provider
        self.provider = ConnectProvider(self.charm)

    def _update_status(self, event: EventBase) -> None:
        """Handler for `update-status` event."""
        service_health = self.charm.connect_manager.healthy

        if service_health:
            self.charm._set_status(ConnectStatus.ACTIVE)
            self.charm.unit.set_ports(self.context.rest_port)
            logger.info(f"Connector(s) Status: {self.charm.connect_manager.connectors}")
        elif service_health.status_code == 503:
            self.charm._set_status(ConnectStatus.SERVICE_STARTING)
        elif service_health.status_code == 500:
            self.charm._set_status(ConnectStatus.SERVICE_UNHEALTHY)
        elif self.context.ready:
            self.charm._set_status(ConnectStatus.SERVICE_NOT_RUNNING)
        else:
            self.charm._set_status(self.context.status)

        if not isinstance(event, UpdateStatusEvent):
            return

        # for plugins update if needed
        self.charm.on.config_changed.emit()

    def _on_config_changed(self, event: ConfigChangedEvent) -> None:
        """Handler for `config-changed` event."""
        if not self.workload.container_can_connect:
            event.defer()
            return

        self.charm.reconcile()

        if not self.context.ready:
            event.defer()
            return

        self._update_status(event)

    def enable_auth(self) -> None:
        """Sets up authentication, including admin user credentials, and initiates internal credential stores on peer worker units."""
        if self.charm.unit.is_leader() and not self.context.peer_workers.admin_password:
            # create admin password
            admin_password = self.workload.generate_password()
            self.context.peer_workers.update(
                {self.context.peer_workers.ADMIN_PASSWORD: admin_password}
            )

        # Update internal credentials store
        self.charm.auth_manager.update(credentials=self.context.credentials)

    def update_clients_data(self) -> None:
        """Updates all clients with latest relation data."""
        if not self.charm.unit.is_leader():
            return

        loaded_plugins = self.charm.connect_manager.loaded_client_plugins

        for client in self.context.clients.values():
            if not client.password:
                logger.debug(
                    f"Skipping update of {client.username}, user has not yet been added..."
                )
                continue

            if (
                client.username not in loaded_plugins
                and client.plugin_url != PLUGIN_URL_NOT_REQUIRED
            ):
                continue

            if set(client.endpoints.split(",")) == set(self.context.rest_endpoints.split(",")):
                continue

            client.update(
                {
                    "endpoints": self.context.rest_endpoints,
                    "username": client.username,
                    "password": client.password,
                    "tls": "enabled" if self.context.tls_enabled else "disabled",
                    "tls-ca": (
                        self.context.worker_unit.tls.ca if self.context.tls_enabled else "disabled"
                    ),
                }
            )

    def update_plugins(self) -> None:
        """Attempts to update client plugins on this worker."""
        loaded_clients = self.charm.connect_manager.loaded_client_plugins
        update_set = set()

        for client in self.context.clients.values():
            if client.username in loaded_clients or client.plugin_url == PLUGIN_URL_NOT_REQUIRED:
                continue

            try:
                self.charm.connect_manager.load_plugin_from_url(
                    client.plugin_url, path_prefix=client.username
                )
            except PluginDownloadFailedError as e:
                logger.warning(f"Unable to fetch the plugin for {client.username}: {e}")
                continue

            update_set.add(client)

        if update_set:
            self.context.worker_unit.should_restart = True
