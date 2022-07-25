#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Application charm that connects to database charms.

This charm is meant to be used only for testing
of the libraries in this repository.
"""

import logging

from ops.charm import CharmBase, RelationEvent
from ops.main import main
from ops.model import ActiveStatus

logger = logging.getLogger(__name__)


CHARM_KEY = "app"
PEER = "cluster"
REL_NAME = "kafka"


class ApplicationCharm(CharmBase):
    """Application charm that connects to database charms."""

    def __init__(self, *args):
        super().__init__(*args)
        self.name = CHARM_KEY

        self.framework.observe(getattr(self.on, "start"), self._on_start)
        self.framework.observe(self.on[REL_NAME].relation_changed, self._log)
        self.framework.observe(self.on[REL_NAME].relation_broken, self._log)
        self.framework.observe(self.on[REL_NAME].relation_joined, self._set_data)

    @property
    def relation(self):
        return self.model.get_relation(REL_NAME)

    def _on_start(self, _) -> None:
        self.unit.status = ActiveStatus()

    def _set_data(self, _) -> None:
        return

    def _log(self, event: RelationEvent):
        return


if __name__ == "__main__":
    main(ApplicationCharm)
