#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

import logging
import subprocess

from ops.charm import CharmBase
from ops.main import main
from ops.model import MaintenanceStatus, ActiveStatus, BlockedStatus
from kafka_helpers import install_packages

logger = logging.getLogger(__name__)


class KafkaCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.name = "kafka"

        self.framework.observe(getattr(self.on, "install"), self._on_install)
        self.framework.observe(getattr(self.on, "cluster_relation_joined"), self._on_cluster_relation_joined)
        self.framework.observe(getattr(self.on, "leader_elected"), self._on_leader_elected)

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


if __name__ == "__main__":
    main(KafkaCharm)
