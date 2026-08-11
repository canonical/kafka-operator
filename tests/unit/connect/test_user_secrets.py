import dataclasses
import logging
from typing import cast
from unittest.mock import patch

import pytest
from ops.testing import Context, PeerRelation, Relation, Secret, State

from .helpers import KAFKA_CLIENT_REL, PEER_REL, ConnectCharm

logger = logging.getLogger(__name__)
AUTH_CONFIG_KEY = "system-users"


@pytest.mark.parametrize("secret_provided", [True, False])
def test_set_credentials(
    ctx: Context,
    base_state: State,
    kafka_client_rel: dict,
    secret_provided: bool,
    active_service,
    restart_rel,
) -> None:
    """Tests setting username/passwords through secrets."""
    auth_secret = Secret(
        label="auth_secret",
        tracked_content={"admin": "newpass"},
    )
    kafka_rel = Relation(KAFKA_CLIENT_REL, KAFKA_CLIENT_REL, remote_app_data=kafka_client_rel)
    peer_rel = PeerRelation(PEER_REL, PEER_REL, local_app_data={"admin-password": "oldpass"})
    state_in = dataclasses.replace(
        base_state,
        relations=[kafka_rel, peer_rel, restart_rel],
        secrets=[auth_secret],
        config={AUTH_CONFIG_KEY: auth_secret.id} if secret_provided else {},
    )

    with (
        ctx(ctx.on.secret_changed(auth_secret), state_in) as mgr,
        patch("single_kernel_kafka.managers.connect.ConnectManager.restart_worker") as _restart,
    ):
        charm: ConnectCharm = cast(ConnectCharm, mgr.charm)
        previous_password = charm.context.peer_workers.admin_password
        _ = mgr.run()

    assert previous_password == "oldpass"

    if secret_provided:
        assert charm.context.peer_workers.admin_password != previous_password
        assert charm.context.peer_workers.admin_password == "newpass"
        _restart.assert_called_once()
    else:
        assert charm.context.peer_workers.admin_password == previous_password
