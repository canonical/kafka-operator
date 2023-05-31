#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path
from unittest.mock import Mock, PropertyMock, patch

import pytest
import yaml
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.testing import Harness
from tenacity.wait import wait_none

from charm import KafkaCharm
from health import KafkaHealth
from literals import CHARM_KEY, INTERNAL_USERS, PEER, REL_NAME, ZK

logger = logging.getLogger(__name__)

CONFIG = str(yaml.safe_load(Path("./config.yaml").read_text()))
ACTIONS = str(yaml.safe_load(Path("./actions.yaml").read_text()))
METADATA = str(yaml.safe_load(Path("./metadata.yaml").read_text()))


@pytest.fixture
def harness():
    harness = Harness(KafkaCharm, meta=METADATA)
    harness.add_relation("restart", CHARM_KEY)
    harness._update_config(
        {
            "log_retention_ms": "-1",
            "compression_type": "producer",
        }
    )
    harness.begin()
    storage_metadata = getattr(harness.charm, "meta").storages["data"]
    min_storages = storage_metadata.multiple_range[0] if storage_metadata.multiple_range else 0
    with harness.hooks_disabled():
        harness.add_storage(storage_name="data", count=min_storages, attach=True)

    return harness


def test_ready_to_start_maintenance_no_peer_relation(harness):
    assert not harness.charm.ready_to_start
    assert isinstance(harness.charm.unit.status, MaintenanceStatus)


def test_ready_to_start_blocks_no_zookeeper_relation(harness):
    with harness.hooks_disabled():
        harness.add_relation(PEER, CHARM_KEY)

    assert not harness.charm.ready_to_start
    assert isinstance(harness.charm.unit.status, BlockedStatus)


def test_ready_to_start_waits_no_zookeeper_data(harness):
    with harness.hooks_disabled():
        harness.add_relation(PEER, CHARM_KEY)
        harness.add_relation(ZK, ZK)

    assert not harness.charm.ready_to_start
    assert isinstance(harness.charm.unit.status, WaitingStatus)


def test_ready_to_start_waits_no_user_credentials(harness, zk_data):
    with harness.hooks_disabled():
        harness.add_relation(PEER, CHARM_KEY)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)

    assert not harness.charm.ready_to_start
    assert isinstance(harness.charm.unit.status, WaitingStatus)


def test_ready_to_start_blocks_mismatch_tls(harness, zk_data, passwords_data):
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, {"tls": "enabled"})

    assert not harness.charm.ready_to_start
    assert isinstance(harness.charm.unit.status, BlockedStatus)


def test_ready_to_start_succeeds(harness, zk_data, passwords_data):
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)

    assert harness.charm.ready_to_start


def test_healthy_fails_if_not_ready_to_start(harness, zk_data, passwords_data):
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, {"tls": "enabled"})

    assert not harness.charm.healthy
    assert isinstance(harness.charm.unit.status, BlockedStatus)


def test_healthy_fails_if_snap_not_active(harness, zk_data, passwords_data):
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)

    with patch("snap.KafkaSnap.active", return_value=False) as patched_snap_active:
        assert not harness.charm.healthy
        assert patched_snap_active.call_count == 1
        assert isinstance(harness.charm.unit.status, BlockedStatus)


def test_healthy_does_not_ping_zk_if_snap_not_active(harness, zk_data, passwords_data):
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)

    with (
        patch("snap.KafkaSnap.active", return_value=False),
        patch("charm.broker_active", return_value=False) as patched_broker_active,
    ):
        assert patched_broker_active.call_count == 0


def test_healthy_succeeds(harness, zk_data, passwords_data):
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)

    with (
        patch("snap.KafkaSnap.active", return_value=True),
        patch("charm.broker_active", return_value=True),
    ):
        assert harness.charm.healthy


def test_update_status_blocks_if_broker_not_active(harness, zk_data, passwords_data):
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)

    with (
        patch("snap.KafkaSnap.active", return_value=True),
        patch("charm.broker_active", return_value=False) as patched_broker_active,
    ):
        harness.charm.on.update_status.emit()
        assert patched_broker_active.call_count == 1
        assert isinstance(harness.charm.unit.status, BlockedStatus)


def test_update_status_blocks_if_no_service(harness, zk_data, passwords_data):
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)

    with (
        patch(
            "snap.snap.Snap.logs",
            return_value="2023-04-13T13:11:43+01:00 juju.fetch-oci[840]: /usr/bin/timeout",
        ),
        patch("charm.KafkaCharm.healthy", return_value=True),
        patch("charm.broker_active", return_value=True),
    ):
        harness.charm.on.update_status.emit()
        assert isinstance(harness.charm.unit.status, BlockedStatus)


def test_update_status_sets_active(harness, zk_data, passwords_data):
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)

    with (
        patch("snap.KafkaSnap.active", return_value=True),
        patch("charm.broker_active", return_value=True),
        patch("health.KafkaHealth.machine_configured", return_value=True),
    ):
        harness.charm.on.update_status.emit()
        assert isinstance(harness.charm.unit.status, ActiveStatus)


def test_storage_add_does_nothing_if_snap_not_active(harness, zk_data, passwords_data):
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")
        harness.set_leader(True)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)

    with (
        patch("snap.KafkaSnap.active", return_value=False),
        patch("charm.KafkaCharm._disable_enable_restart") as patched_restart,
        patch("charm.set_snap_ownership"),
        patch("charm.set_snap_mode_bits"),
    ):
        harness.add_storage(storage_name="data", count=2)
        harness.attach_storage(storage_id="data/1")

        assert patched_restart.call_count == 0


def test_storage_add_defers_if_service_not_healthy(harness, zk_data, passwords_data):
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")
        harness.set_leader(True)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)

    with (
        patch("snap.KafkaSnap.active", return_value=True),
        patch("charm.KafkaCharm.healthy", return_value=False),
        patch("charm.KafkaCharm._disable_enable_restart") as patched_restart,
        patch("ops.framework.EventBase.defer") as patched_defer,
        patch("charm.set_snap_ownership"),
        patch("charm.set_snap_mode_bits"),
    ):
        harness.add_storage(storage_name="data", count=2)
        harness.attach_storage(storage_id="data/1")

        assert patched_restart.call_count == 0
        assert patched_defer.call_count == 1


def test_storage_add_disableenables_and_starts(harness, zk_data, passwords_data):
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")
        harness.set_leader(True)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)

    with (
        patch("snap.KafkaSnap.active", return_value=True),
        patch("charm.KafkaCharm.healthy", new_callable=PropertyMock(return_value=True)),
        patch("config.KafkaConfig.set_server_properties"),
        patch("config.KafkaConfig.set_client_properties"),
        patch("charm.safe_get_file", return_value=["gandalf=grey"]),
        patch("snap.KafkaSnap.disable_enable") as patched_disable_enable,
        patch("snap.KafkaSnap.start_snap_service") as patched_start,
        patch("ops.framework.EventBase.defer") as patched_defer,
        patch("charm.set_snap_ownership"),
        patch("charm.set_snap_mode_bits"),
    ):
        harness.add_storage(storage_name="data", count=2)
        harness.attach_storage(storage_id="data/1")

        assert patched_disable_enable.call_count == 1
        assert patched_start.call_count == 1
        assert patched_defer.call_count == 0


def test_storage_detaching_disableenables_and_starts(harness, zk_data, passwords_data):
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")
        harness.set_leader(True)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)
        harness.add_storage(storage_name="data", count=2)
        harness.attach_storage(storage_id="data/1")

    with (
        patch("snap.KafkaSnap.active", return_value=True),
        patch("charm.KafkaCharm.healthy", new_callable=PropertyMock(return_value=True)),
        patch("config.KafkaConfig.set_server_properties"),
        patch("config.KafkaConfig.set_client_properties"),
        patch("charm.safe_get_file", return_value=["gandalf=grey"]),
        patch("snap.KafkaSnap.disable_enable") as patched_disable_enable,
        patch("snap.KafkaSnap.start_snap_service") as patched_start,
        patch("ops.framework.EventBase.defer") as patched_defer,
    ):
        harness.detach_storage(storage_id="data/1")

        assert patched_disable_enable.call_count == 1
        assert patched_start.call_count == 1
        assert patched_defer.call_count == 0


def test_install_sets_env_vars(harness):
    """Checks KAFKA_OPTS and other vars are written to /etc/environment on install hook."""
    with (
        patch("snap.KafkaSnap.install"),
        patch("config.KafkaConfig.set_environment") as patched_kafka_opts,
    ):
        harness.charm.on.install.emit()

        patched_kafka_opts.assert_called_once()


def test_install_waits_until_zookeeper_relation(harness):
    """Checks unit goes to WaitingStatus without ZK relation on install hook."""
    with (
        patch("snap.KafkaSnap.install"),
        patch("config.KafkaConfig.set_environment"),
    ):
        harness.charm.on.install.emit()
        assert isinstance(harness.charm.unit.status, BlockedStatus)


def test_install_blocks_snap_install_failure(harness):
    """Checks unit goes to BlockedStatus after snap failure on install hook."""
    with (
        patch("snap.KafkaSnap.install", return_value=False),
        patch("config.KafkaConfig.set_environment"),
    ):
        harness.charm.on.install.emit()
        assert isinstance(harness.charm.unit.status, BlockedStatus)


def test_zookeeper_changed_sets_passwords_and_creates_users_with_zk(harness, zk_data):
    """Checks inter-broker passwords are created on zookeeper-changed hook using zk auth."""
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")
        harness.set_leader(True)
        zk_rel_id = harness.add_relation(ZK, ZK)

    with (
        patch("auth.KafkaAuth.add_user") as patched_add_user,
        patch("config.KafkaConfig.set_zk_jaas_config") as patched_set_zk_jaas,
        patch("config.KafkaConfig.set_server_properties") as patched_set_server_properties,
    ):
        harness.update_relation_data(zk_rel_id, ZK, zk_data)

        for user in INTERNAL_USERS:
            assert harness.charm.app_peer_data.get(f"{user}-password", None)

        patched_set_zk_jaas.assert_called_once()
        patched_set_server_properties.assert_called_once()

        # checks all users are INTERNAL only
        for call in patched_add_user.kwargs.get("username", []):
            assert call in INTERNAL_USERS

        # checks all users added are added with --zookeeper auth
        for call in patched_add_user.kwargs.get("zk_auth", False):
            assert True


def test_zookeeper_joined_sets_chroot(harness):
    """Checks chroot is added to ZK relation data on ZKrelationjoined hook."""
    harness.add_relation(PEER, CHARM_KEY)
    harness.set_leader(True)
    zk_rel_id = harness.add_relation(ZK, ZK)
    harness.add_relation_unit(zk_rel_id, f"{ZK}/0")

    assert CHARM_KEY in harness.charm.model.relations[ZK][0].data[harness.charm.app].get(
        "chroot", ""
    )


def test_zookeeper_broken_stops_service(harness):
    """Checks chroot is added to ZK relation data on ZKrelationjoined hook."""
    harness.add_relation(PEER, CHARM_KEY)
    zk_rel_id = harness.add_relation(ZK, ZK)

    with patch("snap.KafkaSnap.stop_snap_service") as patched_stop_snap_service:
        harness.remove_relation(zk_rel_id)

        patched_stop_snap_service.assert_called_once()
        assert isinstance(harness.charm.unit.status, BlockedStatus)


def test_start_defers_without_zookeeper(harness):
    """Checks event deferred and not lost without ZK relation on start hook."""
    with patch("ops.framework.EventBase.defer") as patched_defer:
        harness.charm.on.start.emit()

        patched_defer.assert_called_once()


def test_start_sets_necessary_config(harness):
    """Checks event writes all needed config to unit on start hook."""
    harness.add_relation(PEER, CHARM_KEY)
    zk_rel_id = harness.add_relation(ZK, ZK)
    harness.set_leader(True)
    harness.add_relation_unit(zk_rel_id, "zookeeper/0")

    with (
        patch("config.KafkaConfig.set_zk_jaas_config") as patched_jaas,
        patch("config.KafkaConfig.set_server_properties") as patched_server_properties,
        patch("config.KafkaConfig.set_client_properties") as patched_client_properties,
        patch("charm.KafkaCharm._update_internal_user"),
        patch("snap.KafkaSnap.start_snap_service"),
        patch("charm.KafkaCharm._on_update_status"),
        patch("charm.KafkaCharm.ready_to_start", return_value=True),
    ):
        harness.update_relation_data(zk_rel_id, ZK, {"username": "glorfindel"})
        harness.charm.on.start.emit()
        patched_jaas.assert_called_once()
        patched_server_properties.assert_called_once()
        patched_client_properties.assert_called_once()


def test_start_does_not_start_if_not_ready(harness):
    """Checks snap service does not start before ready on start hook."""
    harness.add_relation(PEER, CHARM_KEY)
    zk_rel_id = harness.add_relation(ZK, ZK)
    harness.add_relation_unit(zk_rel_id, "zookeeper/0")

    with (
        patch("charm.KafkaCharm.ready_to_start", new_callable=PropertyMock, return_value=False),
        patch("snap.KafkaSnap.start_snap_service") as patched_start_snap_service,
        patch("ops.framework.EventBase.defer") as patched_defer,
        patch("config.KafkaConfig.zookeeper_connected", return_value=True),
        patch("config.KafkaConfig.internal_user_credentials", return_value="orthanc"),
    ):
        harness.charm.on.start.emit()

        patched_start_snap_service.assert_not_called()
        patched_defer.assert_called()


def test_start_does_not_start_if_not_same_tls_as_zk(harness):
    """Checks snap service does not start if mismatch Kafka+ZK TLS on start hook."""
    harness.add_relation(PEER, CHARM_KEY)
    zk_rel_id = harness.add_relation(ZK, ZK)
    harness.add_relation_unit(zk_rel_id, "zookeeper/0")

    with (
        patch("auth.KafkaAuth.add_user"),
        patch("config.KafkaConfig.set_zk_jaas_config"),
        patch("config.KafkaConfig.set_server_properties"),
        patch("config.KafkaConfig.set_client_properties"),
        patch("snap.KafkaSnap.start_snap_service") as patched_start_snap_service,
        patch("config.KafkaConfig.zookeeper_connected", return_value=True),
        patch("config.KafkaConfig.internal_user_credentials", return_value="orthanc"),
        patch("tls.KafkaTLS.enabled", return_value=True),
    ):
        harness.charm.on.start.emit()

        patched_start_snap_service.assert_not_called()
        assert isinstance(harness.charm.unit.status, BlockedStatus)


def test_start_does_not_start_if_leader_has_not_set_creds(harness):
    """Checks snap service does not start without inter-broker creds on start hook."""
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    zk_rel_id = harness.add_relation(ZK, ZK)
    harness.add_relation_unit(zk_rel_id, "zookeeper/0")
    harness.update_relation_data(peer_rel_id, CHARM_KEY, {"sync-password": "mellon"})

    with (
        patch("config.KafkaConfig.set_zk_jaas_config"),
        patch("config.KafkaConfig.set_server_properties"),
        patch("config.KafkaConfig.set_client_properties"),
        patch("snap.KafkaSnap.start_snap_service") as patched_start_snap_service,
        patch("config.KafkaConfig.zookeeper_connected", return_value=True),
    ):
        harness.charm.on.start.emit()

        patched_start_snap_service.assert_not_called()
        assert isinstance(harness.charm.unit.status, WaitingStatus)


def test_start_blocks_if_service_failed_silently(harness):
    """Checks unit is not ActiveStatus if snap service start failed silently on start hook."""
    harness.add_relation(PEER, CHARM_KEY)
    zk_rel_id = harness.add_relation(ZK, ZK)
    harness.add_relation_unit(zk_rel_id, "zookeeper/0")
    harness.set_leader(True)

    with (
        patch("auth.KafkaAuth.add_user"),
        patch("config.KafkaConfig.set_zk_jaas_config"),
        patch("config.KafkaConfig.set_server_properties"),
        patch("config.KafkaConfig.set_client_properties"),
        patch("snap.KafkaSnap.start_snap_service") as patched_start_snap_service,
        patch("charm.broker_active", return_value=False) as patched_broker_active,
        patch("config.KafkaConfig.internal_user_credentials", return_value="orthanc"),
        patch("config.KafkaConfig.zookeeper_connected", return_value=True),
    ):
        patched_broker_active.retry.wait = wait_none
        harness.charm.on.start.emit()

        patched_start_snap_service.assert_called_once()
        assert isinstance(harness.charm.unit.status, BlockedStatus)


def test_config_changed_updates_server_properties(harness):
    """Checks that new charm/unit config writes server config to unit on config changed hook."""
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")

    with (
        patch(
            "config.KafkaConfig.server_properties",
            new_callable=PropertyMock,
            return_value=["gandalf=white"],
        ),
        patch("charm.KafkaCharm.ready_to_start", new_callable=PropertyMock, return_value=True),
        patch("charm.KafkaCharm.healthy", new_callable=PropertyMock, return_value=True),
        patch("charm.safe_get_file", return_value=["gandalf=grey"]),
        patch("config.KafkaConfig.set_server_properties") as set_server_properties,
        patch("config.KafkaConfig.set_client_properties"),
    ):
        harness.charm.on.config_changed.emit()

        set_server_properties.assert_called_once()


def test_config_changed_updates_client_properties(harness):
    """Checks that new charm/unit config writes client config to unit on config changed hook."""
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")

    with (
        patch(
            "config.KafkaConfig.client_properties",
            new_callable=PropertyMock,
            return_value=["gandalf=white"],
        ),
        patch(
            "config.KafkaConfig.server_properties",
            new_callable=PropertyMock,
            return_value=["sauron=bad"],
        ),
        patch("charm.KafkaCharm.ready_to_start", new_callable=PropertyMock, return_value=True),
        patch("charm.KafkaCharm.healthy", new_callable=PropertyMock, return_value=True),
        patch("charm.safe_get_file", return_value=["gandalf=grey"]),
        patch("config.KafkaConfig.set_server_properties"),
        patch("config.KafkaConfig.set_client_properties") as set_client_properties,
    ):
        harness.charm.on.config_changed.emit()

        set_client_properties.assert_called_once()


def test_config_changed_updates_client_data(harness):
    """Checks that provided relation data updates on config changed hook."""
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")
    harness.add_relation(REL_NAME, "app")

    with (
        patch(
            "config.KafkaConfig.server_properties",
            new_callable=PropertyMock,
            return_value=["gandalf=white"],
        ),
        patch("charm.KafkaCharm.ready_to_start", new_callable=PropertyMock, return_value=True),
        patch("charm.safe_get_file", return_value=["gandalf=white"]),
        patch("provider.KafkaProvider.update_connection_info") as patched_update_connection_info,
        patch("charm.KafkaCharm.healthy", new_callable=PropertyMock, return_value=True),
        patch("config.KafkaConfig.set_client_properties") as patched_set_client_properties,
    ):
        harness.set_leader(True)
        harness.charm.on.config_changed.emit()

        patched_set_client_properties.assert_called_once()
        patched_update_connection_info.assert_called_once()


def test_config_changed_restarts(harness):
    """Checks units rolling-restat on config changed hook."""
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")
    harness.set_leader(True)
    zk_rel_id = harness.add_relation(ZK, ZK)
    harness.add_relation_unit(zk_rel_id, f"{ZK}/0")

    with (
        patch(
            "config.KafkaConfig.server_properties",
            new_callable=PropertyMock,
            return_value=["gandalf=grey"],
        ),
        patch("charm.KafkaCharm.ready_to_start", new_callable=PropertyMock, return_value=True),
        patch("charm.safe_get_file", return_value=["gandalf=white"]),
        patch("config.safe_write_to_file", return_value=None),
        patch("snap.KafkaSnap.restart_snap_service") as patched_restart_snap_service,
        patch("charm.broker_active", return_value=True),
        patch("config.KafkaConfig.zookeeper_connected", return_value=True),
        patch("auth.KafkaAuth.add_user"),
        patch("charm.KafkaCharm.healthy", new_callable=PropertyMock, return_value=True),
        patch("config.KafkaConfig.set_zk_jaas_config"),
        patch("config.KafkaConfig.set_server_properties"),
    ):
        harness.update_relation_data(zk_rel_id, ZK, {"username": "glorfindel"})

        patched_restart_snap_service.reset_mock()

        harness.charm.on.config_changed.emit()

        patched_restart_snap_service.assert_called_once()


@pytest.mark.parametrize("underminisrpartitioncount,deferred", [("1.0", True), ("0.0", False)])
def test_upgrade_charm_succeeds(harness, underminisrpartitioncount, deferred):
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")
    harness.set_leader(True)
    zk_rel_id = harness.add_relation(ZK, ZK)
    harness.add_relation_unit(zk_rel_id, f"{ZK}/0")

    KafkaHealth.partitions_in_sync.retry.wait = wait_none()
    mock_response = Mock()
    mock_response.text = f"""
        kafka_server_replicamanager_underminisrpartitioncount {underminisrpartitioncount}
    """

    with (
        patch("charm.KafkaCharm.healthy", new_callable=PropertyMock, return_value=True),
        patch("snap.KafkaSnap.restart_snap_service") as patched_restart_snap_service,
        patch("ops.framework.EventBase.defer") as patched_defer,
        patch("requests.get", return_value=mock_response),
    ):
        harness.charm.on.upgrade_charm.emit()

        assert patched_restart_snap_service.call_count
        assert bool(patched_defer.call_count) == deferred
