#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed Machine Operator for Kafka."""

import logging
import subprocess

from charms.operator_libs_linux.v0.apt import PackageNotFoundError
from charms.operator_libs_linux.v1.snap import SnapError
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, Relation

from charms.kafka.v0.kafka_helpers import install_kafka_snap, merge_config

logger = logging.getLogger(__name__)


class KafkaCharm(CharmBase):
    """Charmed Operator for Kafka."""

    def __init__(self, *args):
        super().__init__(*args)
        self.name = "kafka"

        self.framework.observe(getattr(self.on, "install"), self._on_install)
        self.framework.observe(
            getattr(self.on, "cluster_relation_joined"), self._on_cluster_relation_joined
        )
        self.framework.observe(getattr(self.on, "leader_elected"), self._on_leader_elected)
        self.framework.observe(
            getattr(self.on, "get_server_properties_action"), self._on_get_server_properties_action
        )

    @property
    def _relation(self) -> Relation:
        return self.model.get_relation("cluster")

    def _on_install(self, _) -> None:
        """Handler for on_install event."""
        try:
            self.unit.status = MaintenanceStatus("installing Kafka snap")
            install_kafka_snap()
            self.unit.status = ActiveStatus()
        except (SnapError, PackageNotFoundError):
            self.unit.status = BlockedStatus("failed to install Kakfa snap")

    def _on_leader_elected(self, _) -> None:
        return

    def _on_cluster_relation_joined(self, _) -> None:
        return

    def _on_config_changed(self, _) -> None:
        """Handler for config_changed event."""
        self._start_services()

        if not isinstance(self.unit.status, BlockedStatus):
            self.unit.status = ActiveStatus()

    def _start_services(self) -> None:
        return

    def _on_get_server_properties_action(self, event) -> None:
        """Handler for users to copy currently active config for passing to `juju config`."""
        # TODO: generalise this for arbitrary *.properties
        default_server_config_path = "/snap/kafka/current/opt/kafka/config/server.properties"
        snap_server_config_path = "/var/snap/kafka/common/server.properties"

        msg = merge_config(default=default_server_config_path, override=snap_server_config_path)

        event.set_results({"server-properties": msg})


if __name__ == "__main__":
    main(KafkaCharm)
