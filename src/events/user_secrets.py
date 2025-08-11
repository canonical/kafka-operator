#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Event Handler for user-defined secret events.

Internal user management could be done by defining secrets
and granting their access to the charm.

The flow for defining secrets and granting access to the charm would be as below:

    juju add-secret my-auth admin=goodpass
    # secret:cvh7kruupa1s46bqvuig
    juju grant-secret my-auth kafka
    juju config kafka system-users=secret:cvh7kruupa1s46bqvuig

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

from literals import INTERNAL_USERS

if TYPE_CHECKING:
    from charm import KafkaCharm
    from events.broker import BrokerOperator


logger = logging.getLogger(__name__)


class SecretsHandler(Object):
    """Handler for events related to user-defined secrets."""

    def __init__(self, dependent: "BrokerOperator") -> None:
        super().__init__(dependent.charm, "connect-secrets")
        self.dependent = dependent
        self.charm: "KafkaCharm" = dependent.charm
        self.state = self.charm.state
        self.workload = self.charm.workload

        self.framework.observe(getattr(self.charm.on, "config_changed"), self._on_secret_changed)
        self.framework.observe(getattr(self.charm.on, "secret_changed"), self._on_secret_changed)

    def _on_secret_changed(self, event: SecretChangedEvent) -> None:
        """Handle the `secret_changed` event."""
        if not self.model.unit.is_leader():
            return

        if not (credentials := self.load_auth_secret()):
            return

        if not all(
            [
                self.dependent.upgrade.idle,
                self.dependent.healthy,
                self.workload.container_can_connect,
            ]
        ):
            event.defer()
            return

        saved_state = self.state.cluster.internal_user_credentials
        changed = {u for u in credentials if credentials[u] != saved_state.get(u)}

        if not changed:
            return

        logger.info(f"Credentials change detected for {changed}")

        # Store the password on application databag
        for username in changed:
            new_password = credentials[username]
            self.state.cluster.relation_data.update({f"{username}-password": new_password})

        try:
            for username in changed:
                self.dependent.auth_manager.add_user(
                    username=username, password=credentials[username]
                )
        except Exception as e:
            logger.error(f"unable to set password for {username}: {e}")
            return

        # This will update peer-cluster data
        self.charm.on.config_changed.emit()

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
            if username in INTERNAL_USERS
        }

        denied_users = set(secret_content) - set(creds)

        if denied_users:
            logger.error(f"Can't set password for non-internal user(s) {', '.join(denied_users)}")

        return creds
