#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Event Handler for user-defined secret events.

User management on the Kafka Connect REST API could be done by defining secrets
and granting their access to the charm.

The flow for defining secrets and granting access to the charm would be as below:

    juju add-secret my-auth admin=goodpass
    # secret:cvh7kruupa1s46bqvuig
    juju grant-secret my-auth kafka-connect
    juju config kafka-connect system-users=secret:cvh7kruupa1s46bqvuig

And the update flow would be as simple as:

    juju update-secret my-auth admin=Str0ng_pass
"""

import logging
from typing import TYPE_CHECKING

from ops import ModelError, SecretNotFoundError
from ops.charm import (
    SecretChangedEvent,
)
from ops.framework import Object

if TYPE_CHECKING:
    from ...core.connect_models import ConnectCharmBase


logger = logging.getLogger(__name__)


class SecretsHandler(Object):
    """Handler for events related to user-defined secrets."""

    def __init__(self, charm: "ConnectCharmBase") -> None:
        super().__init__(charm, "connect-secrets")
        self.charm: "ConnectCharmBase" = charm
        self.context = charm.context
        self.workload = charm.workload

        self.framework.observe(getattr(self.charm.on, "config_changed"), self._on_secret_changed)
        self.framework.observe(getattr(self.charm.on, "secret_changed"), self._on_secret_changed)

    def _on_secret_changed(self, _: SecretChangedEvent) -> None:
        """Handle the `secret_changed` event."""
        credentials = self.load_auth_secret()
        saved_state = self.charm.auth_manager.credentials
        changed = {u for u in credentials if credentials[u] != saved_state.get(u)}
        removed = {
            u
            for u in saved_state
            if u not in credentials
            and u != self.context.peer_workers.ADMIN_USERNAME
            and not u.startswith("relation-")
        }  # removed does not have functionality right now, since we only allow internal user.

        if not changed and not removed:
            return

        logger.info(f"Credentials change detected for {changed}")

        if self.context.peer_workers.ADMIN_USERNAME in changed and self.charm.unit.is_leader():
            self.context.peer_workers.update(
                {
                    self.context.peer_workers.ADMIN_PASSWORD: credentials[
                        self.context.peer_workers.ADMIN_USERNAME
                    ]
                }
            )

        if changed:
            self.charm.auth_manager.update(credentials)

        for user in removed:
            self.charm.auth_manager.remove_user(user)

        self.context.worker_unit.should_restart = True
        self.charm.reconcile()

    def load_auth_secret(self) -> dict[str, str]:
        """Loads user-defined credentials from the secrets."""
        if not (secret_id := self.charm.config.system_users):
            return {}

        try:
            secret_content = self.model.get_secret(id=secret_id).get_content(refresh=True)
        except (SecretNotFoundError, ModelError) as e:
            logging.error(f"Failed to fetch the secret, details: {e}")
            return {}

        creds = {
            username: password
            for username, password in secret_content.items()
            if username == self.context.peer_workers.ADMIN_USERNAME
        }

        return creds
