#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""KafkaHandler class and methods."""

import logging
from typing import TYPE_CHECKING

from charms.data_platform_libs.v0.data_interfaces import (
    KafkaRequirerEventHandlers,
)
from ops.charm import RelationBrokenEvent, RelationChangedEvent, RelationCreatedEvent
from ops.framework import Object

from ...core.literals import ConnectLiterals, ConnectStatus
from ...managers.connect import KafkaClient

if TYPE_CHECKING:
    from ...core.connect_models import ConnectCharmBase


logger = logging.getLogger(__name__)


class KafkaHandler(Object):
    """Handler for events on Kafka cluster relation."""

    def __init__(self, charm: "ConnectCharmBase") -> None:
        super().__init__(charm, "kafka_client")
        self.charm: "ConnectCharmBase" = charm
        self.context = charm.context

        self.kafka_manager = KafkaClient(context=self.context, workload=charm.workload)
        self.event_handler = KafkaRequirerEventHandlers(charm, self.context.kafka_client_interface)

        self.framework.observe(
            self.charm.on[ConnectLiterals.KAFKA_CLIENT_REL].relation_created,
            self._on_relation_created,
        )
        self.framework.observe(
            self.charm.on[ConnectLiterals.KAFKA_CLIENT_REL].relation_broken,
            self._on_relation_broken,
        )
        self.framework.observe(
            self.charm.on[ConnectLiterals.KAFKA_CLIENT_REL].relation_changed,
            self._on_relation_changed,
        )

    def _on_relation_created(self, event: RelationCreatedEvent) -> None:
        """Handler for `kafka-client-relation-created` event."""
        if not self.kafka_manager.health_check():
            self.charm._set_status(ConnectStatus.NO_KAFKA_CREDENTIALS)
            event.defer()
            return

        self.charm.on.config_changed.emit()

    def _on_relation_changed(self, event: RelationChangedEvent) -> None:
        """Handler for `kafka-client-relation-changed` event."""
        if self.context.kafka_client.tls_enabled and self.context.kafka_client.broker_ca:
            # Import broker CA to truststore if not done.
            tls_context = self.context.worker_unit.tls
            truststore_password = (
                tls_context.truststore_password or self.charm.workload.generate_password()
            )
            self.charm.workload.write(
                f"{ConnectLiterals.TRUSTSTORE_PASSWORD_KEY}={truststore_password}",
                self.charm.workload.connect_paths.truststore_password,
            )
            self.charm.context.worker_unit.update(
                {tls_context.TRUSTSTORE_PASSWORD: truststore_password}
            )

            # Compatibility: Kafka 3 sends `enabled` on `tls-ca` field.
            if self.charm.context.kafka_client.broker_ca != "enabled":
                self.charm.tls_manager.import_cert(
                    tls_context.BROKER_CA,
                    f"{tls_context.BROKER_CA}.pem",
                    cert_content=self.context.kafka_client.broker_ca,
                )

        self.charm.on.config_changed.emit()

    def _on_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Handler for `kafka-client-relation-broken` event."""
        self.charm._set_status(ConnectStatus.MISSING_KAFKA)
        self.charm.workload.stop()
