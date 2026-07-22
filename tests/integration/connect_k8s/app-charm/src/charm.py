#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Test charm for Apache Kafka Connect integrator (requirer-side) functionality testing."""

import logging
import os

from integrator import Integrator
from ops.charm import CharmBase, CollectStatusEvent, StartEvent, UpdateStatusEvent
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, ModelError

logger = logging.getLogger(__name__)


PORT = 8080
CHARM_KEY = "integrator"
PLUGIN_RESOURCE_KEY = "connect-plugin"


class TestIntegratorCharm(CharmBase):
    """Test Integrator Charm which implements the `KafkaConnectRequires` interface."""

    def __init__(self, *args):
        super().__init__(*args)
        self.name = CHARM_KEY

        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.update_status, self._update_status)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.collect_unit_status, self._on_collect_status)
        self.framework.observe(self.on.collect_app_status, self._on_collect_status)

        self.resource_path = f"{self.charm_dir}/src/resources/"

        self.integrator = Integrator(
            self, plugin_server_args=(self.internal_address, PORT, self.resource_path)
        )

    @property
    def internal_address(self) -> str:
        """Returns unit's address."""
        name, id_ = self.unit.name.split("/")
        return f"{name}-{id_}.{name}-endpoints"

    def _on_start(self, _: StartEvent) -> None:
        """Handler for `start` event."""
        if self.integrator.server.health_check():
            return

        self.integrator.server.start()
        logger.info(f"Plugin server started @ {self.integrator.plugin_url}")

    def _update_status(self, event: UpdateStatusEvent) -> None:
        """Handler for `update-status` event."""
        if not self.integrator.server.health_check():
            self.on.start.emit()

        self.integrator.maybe_resume_connector()

    def _on_config_changed(self, _) -> None:
        """Handler for `config-changed` event."""
        resource_path = None
        try:
            resource_path = self.model.resources.fetch(PLUGIN_RESOURCE_KEY)
            os.system(f"mv {resource_path} {self.resource_path}/plugin.tar")
        except RuntimeError as e:
            logger.error(f"Resource {PLUGIN_RESOURCE_KEY} not defined in the charm build.")
            raise e
        except (NameError, ModelError) as e:
            logger.error(f"Resource {PLUGIN_RESOURCE_KEY} not found or could not be downloaded.")
            raise e

    def _on_collect_status(self, event: CollectStatusEvent):
        """Handler for `collect-status` event."""
        if not self.integrator.server.health_check():
            event.add_status(MaintenanceStatus("Setting up the integrator..."))
            return

        if not self.integrator.ready:
            event.add_status(
                BlockedStatus(
                    "Integrator not ready to start, check if all relations are setup successfully."
                )
            )
            return

        try:
            event.add_status(ActiveStatus(self.integrator.connector_status))
        except Exception as e:
            logger.error(e)
            event.add_status(
                BlockedStatus("Task Status: error communicating with Kafka Connect, check logs.")
            )


if __name__ == "__main__":
    main(TestIntegratorCharm)
