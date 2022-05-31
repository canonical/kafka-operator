#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed Machine Operator for Apache Kafka."""

import logging

from charms.kafka.v0.kafka_snap import KafkaSnap
from ops.charm import CharmBase
from ops.main import main
from ops.model import Relation

logger = logging.getLogger(__name__)


class KafkaCharm(CharmBase):
    """Charmed Operator for Kafka."""

    def __init__(self, *args):
        super().__init__(*args)
        self.name = "kafka"
        self.snap = KafkaSnap()

        self.framework.observe(getattr(self.on, "install"), self._on_install)
        self.framework.observe(
            getattr(self.on, "cluster_relation_joined"), self._on_cluster_relation_joined
        )
        self.framework.observe(getattr(self.on, "leader_elected"), self._on_leader_elected)
        self.framework.observe(
            getattr(self.on, "get_server_properties_action"), self._on_get_properties_action
        )
        self.framework.observe(
            getattr(self.on, "get_snap_apps_action"), self._on_get_snap_apps_action
        )
        self.framework.observe(getattr(self.on, "config_changed"), self._on_config_changed)

    @property
    def _relation(self) -> Relation:
        return self.model.get_relation("cluster")

    def _on_install(self, _) -> None:
        """Handler for on_install event."""
        self.unit.status = self.snap.install_kafka_snap()

    def _on_leader_elected(self, _) -> None:
        return

    def _on_cluster_relation_joined(self, _) -> None:
        return

    def _on_config_changed(self, _) -> None:
        """Handler for config_changed event."""
        self._start_service()

    def _start_service(self) -> None:
        """Starts a service made available in the snap - `kafka` or `zookeeper`."""
        self.unit.status = self.snap.start_snap_service(snap_service="kafka")

    def _on_get_properties_action(self, event) -> None:
        """Handler for users to copy currently active config for passing to `juju config`."""
        msg = self.snap.get_merged_properties(property_label="server")
        event.set_results({"properties": msg})

    def _on_get_snap_apps_action(self, event) -> None:
        """Handler for users to retrieve the list of available Kafka snap commands."""
        msg = self.snap.get_kafka_apps()
        event.set_results({"apps": msg})


if __name__ == "__main__":
    main(KafkaCharm)
