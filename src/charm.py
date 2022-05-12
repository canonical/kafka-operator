#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import subprocess

from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus

from kafka_helpers import install_packages, merge_config

logger = logging.getLogger(__name__)


class KafkaCharm(CharmBase):
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
    def _relation(self):
        return self.model.get_relation("cluster")

    def _on_install(self, _) -> None:
        try:
            self.unit.status = MaintenanceStatus("installing packages")
            install_packages()
            self.unit.status = ActiveStatus()
        except:
            self.unit.status = BlockedStatus("failed to install packages")

    def _on_leader_elected(self, _):
        return

    def _on_cluster_relation_joined(self, _):
        return

    def _on_config_changed(self, _) -> None:
        self._start_services()

        if not isinstance(self.unit.status, BlockedStatus):
            self.unit.status = ActiveStatus()

    def _start_services(self) -> None:
        return

    def _run_command(self, cmd: list) -> bool:
        proc = subprocess.Popen(cmd)
        for line in iter(getattr(proc.stdout, "readline"), ""):
            logger.debug(line)
        proc.wait()
        return proc.returncode == 0

    def _on_get_server_properties_action(self, event):
        """Handler for users to copy currently active config for passing to `juju config`"""

        # TODO: generalise this for arbitrary *.properties
        default_server_config_path = "/snap/kafka/current/opt/kafka/config/server.properties"
        snap_server_config_path = "/var/snap/kafka/common/server.properties"

        msg = merge_config(default=default_server_config_path, override=snap_server_config_path)

        event.set_results({"server-properties": msg})


if __name__ == "__main__":
    main(KafkaCharm)
