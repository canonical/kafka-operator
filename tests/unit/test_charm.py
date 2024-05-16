#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import re
from pathlib import Path
from unittest.mock import Mock, PropertyMock, patch

import pytest
import yaml
from ops.model import BlockedStatus
from ops.testing import Harness

from charm import KafkaCharm
from literals import (
    CHARM_KEY,
    CONTAINER,
    INTERNAL_USERS,
    JMX_EXPORTER_PORT,
    PEER,
    REL_NAME,
    SUBSTRATE,
    ZK,
    Status,
)

if SUBSTRATE == "vm":
    from charms.operator_libs_linux.v0.sysctl import ApplyError
    from charms.operator_libs_linux.v1.snap import SnapError

    from literals import OS_REQUIREMENTS

logger = logging.getLogger(__name__)

CONFIG = str(yaml.safe_load(Path("./config.yaml").read_text()))
ACTIONS = str(yaml.safe_load(Path("./actions.yaml").read_text()))
METADATA = str(yaml.safe_load(Path("./metadata.yaml").read_text()))


@pytest.fixture
def harness() -> Harness:
    harness = Harness(KafkaCharm, meta=METADATA, actions=ACTIONS, config=CONFIG)

    if SUBSTRATE == "k8s":
        harness.set_can_connect(CONTAINER, True)

    harness.add_relation("restart", CHARM_KEY)
    harness._update_config(
        {
            "log_retention_ms": "-1",
            "compression_type": "producer",
        }
    )
    harness.begin()
    storage_metadata = getattr(harness.charm, "meta").storages["data"]
    min_storages = storage_metadata.multiple_range[0] if storage_metadata.multiple_range else 1
    with harness.hooks_disabled():
        harness.add_storage(storage_name="data", count=min_storages, attach=True)
    return harness


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="sysctl config not used on K8s")
def test_install_blocks_snap_install_failure(harness: Harness):
    """Checks unit goes to BlockedStatus after snap failure on install hook."""
    with patch("workload.KafkaWorkload.install", return_value=False):
        harness.charm.on.install.emit()
        assert harness.charm.unit.status == Status.SNAP_NOT_INSTALLED.value.status


def test_install_sets_env_vars(harness: Harness, patched_etc_environment):
    """Checks KAFKA_OPTS and other vars are written to /etc/environment on install hook."""
    with patch("workload.KafkaWorkload.install"):
        harness.charm.on.install.emit()
        patched_etc_environment.assert_called_once()


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="sysctl config not used on K8s")
def test_install_configures_os(harness: Harness, patched_sysctl_config):
    with patch("workload.KafkaWorkload.install"):
        harness.charm.on.install.emit()
        patched_sysctl_config.assert_called_once_with(OS_REQUIREMENTS)


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="sysctl config not used on K8s")
def test_install_sets_status_if_os_config_fails(harness: Harness, patched_sysctl_config):
    with patch("workload.KafkaWorkload.install"):
        patched_sysctl_config.side_effect = ApplyError("Error setting values")
        harness.charm.on.install.emit()

        assert harness.charm.unit.status == Status.SYSCONF_NOT_POSSIBLE.value.status


def test_ready_to_start_maintenance_no_peer_relation(harness: Harness):
    harness.charm.on.start.emit()
    assert harness.charm.unit.status == Status.NO_PEER_RELATION.value.status


def test_ready_to_start_blocks_no_zookeeper_relation(harness: Harness):
    with harness.hooks_disabled():
        harness.add_relation(PEER, CHARM_KEY)

    harness.charm.on.start.emit()
    assert harness.charm.unit.status == Status.ZK_NOT_RELATED.value.status


def test_ready_to_start_waits_no_zookeeper_data(harness: Harness):
    with harness.hooks_disabled():
        harness.add_relation(PEER, CHARM_KEY)
        harness.add_relation(ZK, ZK)

    harness.charm.on.start.emit()
    assert harness.charm.unit.status == Status.ZK_NO_DATA.value.status


def test_ready_to_start_waits_no_user_credentials(harness: Harness, zk_data):
    with harness.hooks_disabled():
        harness.add_relation(PEER, CHARM_KEY)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)

    harness.charm.on.start.emit()
    assert harness.charm.unit.status == Status.NO_BROKER_CREDS.value.status


def test_ready_to_start_blocks_mismatch_tls(harness: Harness, zk_data, passwords_data):
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, {"tls": "enabled"})

    harness.charm.on.start.emit()
    assert harness.charm.unit.status == Status.ZK_TLS_MISMATCH.value.status


def test_ready_to_start_succeeds(harness: Harness, zk_data, passwords_data):
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)

    assert harness.charm.state.ready_to_start.value.status == Status.ACTIVE.value.status


def test_healthy_fails_if_not_ready_to_start(harness: Harness, zk_data, passwords_data):
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, {"tls": "enabled"})

    assert not harness.charm.healthy


def test_healthy_fails_if_snap_not_active(harness: Harness, zk_data, passwords_data):
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)

    with patch("workload.KafkaWorkload.active", return_value=False) as patched_snap_active:
        assert not harness.charm.healthy
        assert patched_snap_active.call_count == 1
        if SUBSTRATE == "vm":
            assert harness.charm.unit.status == Status.SNAP_NOT_RUNNING.value.status
        elif SUBSTRATE == "k8s":
            assert harness.charm.unit.status == Status.SERVICE_NOT_RUNNING.value.status


def test_healthy_succeeds(harness: Harness, zk_data, passwords_data):
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)

    with patch("workload.KafkaWorkload.active", return_value=True):
        assert harness.charm.healthy


def test_start_defers_without_zookeeper(harness: Harness):
    """Checks event deferred and not lost without ZK relation on start hook."""
    with patch("ops.framework.EventBase.defer") as patched_defer:
        harness.charm.on.start.emit()

        patched_defer.assert_called_once()


def test_start_sets_necessary_config(harness: Harness, zk_data, passwords_data):
    """Checks event writes all needed config to unit on start hook."""
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.set_leader(True)
        harness.add_relation_unit(zk_rel_id, "zookeeper/0")
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)

    with (
        patch("managers.auth.AuthManager.add_user"),
        patch("managers.config.KafkaConfigManager.set_zk_jaas_config") as patched_jaas,
        patch(
            "managers.config.KafkaConfigManager.set_server_properties"
        ) as patched_server_properties,
        patch(
            "managers.config.KafkaConfigManager.set_client_properties"
        ) as patched_client_properties,
        patch("workload.KafkaWorkload.start"),
        # NOTE: Patching `active` cuts the hook short, as we are only testing properties being set.
        patch("workload.KafkaWorkload.active", return_value=False),
    ):
        harness.charm.on.start.emit()
        patched_jaas.assert_called_once()
        patched_server_properties.assert_called_once()
        patched_client_properties.assert_called_once()


@pytest.mark.skipif(SUBSTRATE == "vm", reason="pebble layer not used on vm")
def test_start_sets_pebble_layer(harness: Harness, zk_data, passwords_data):
    """Checks layer is the expected at start."""
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.set_leader(True)
        harness.add_relation_unit(zk_rel_id, "zookeeper/0")
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)

    with (
        patch("managers.auth.AuthManager.add_user"),
        patch("managers.config.KafkaConfigManager.set_zk_jaas_config"),
        patch("managers.config.KafkaConfigManager.set_server_properties"),
        patch("managers.config.KafkaConfigManager.set_client_properties"),
        # NOTE: Patching `active` cuts the hook short, as we are only testing layer being set.
        patch("workload.KafkaWorkload.active", return_value=False),
    ):
        harness.charm.on.start.emit()
        found_plan = harness.get_container_pebble_plan("kafka").to_dict()
        extra_opts = [
            f"-javaagent:{harness.charm.workload.paths.jmx_prometheus_javaagent}={JMX_EXPORTER_PORT}:{harness.charm.workload.paths.jmx_prometheus_config}",
            f"-Djava.security.auth.login.config={harness.charm.workload.paths.zk_jaas}",
        ]
        command = f"{harness.charm.workload.paths.binaries_path}/bin/kafka-server-start.sh {harness.charm.workload.paths.server_properties}"
        expected_plan = {
            "services": {
                CONTAINER: {
                    "override": "replace",
                    "summary": "kafka",
                    "command": command,
                    "startup": "enabled",
                    "user": "kafka",
                    "group": "kafka",
                    "environment": {
                        "KAFKA_OPTS": " ".join(extra_opts),
                        "JAVA_HOME": "/usr/lib/jvm/java-18-openjdk-amd64",
                        "LOG_DIR": harness.charm.workload.paths.logs_path,
                    },
                }
            },
        }
        assert expected_plan == found_plan


def test_start_does_not_start_if_not_ready(harness: Harness):
    """Checks snap service does not start before ready on start hook."""
    with harness.hooks_disabled():
        harness.add_relation(PEER, CHARM_KEY)

    with (
        patch("workload.KafkaWorkload.start") as patched_start_snap_service,
        patch("ops.framework.EventBase.defer") as patched_defer,
    ):
        harness.charm.on.start.emit()

        patched_start_snap_service.assert_not_called()
        patched_defer.assert_called()


def test_start_does_not_start_if_not_same_tls_as_zk(harness: Harness):
    """Checks snap service does not start if mismatch Kafka+ZK TLS on start hook."""
    harness.add_relation(PEER, CHARM_KEY)
    zk_rel_id = harness.add_relation(ZK, ZK)
    harness.add_relation_unit(zk_rel_id, "zookeeper/0")

    with (
        patch("managers.auth.AuthManager.add_user"),
        patch("workload.KafkaWorkload.start") as patched_start_snap_service,
        patch("core.cluster.ZooKeeper.zookeeper_connected", return_value=True),
        patch("core.models.KafkaCluster.internal_user_credentials", return_value="orthanc"),
        patch("core.models.KafkaCluster.tls_enabled", return_value=True),
    ):
        harness.charm.on.start.emit()

        patched_start_snap_service.assert_not_called()
        assert harness.charm.unit.status == Status.ZK_TLS_MISMATCH.value.status


def test_start_does_not_start_if_leader_has_not_set_creds(harness: Harness):
    """Checks snap service does not start without inter-broker creds on start hook."""
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    zk_rel_id = harness.add_relation(ZK, ZK)
    harness.add_relation_unit(zk_rel_id, "zookeeper/0")
    harness.update_relation_data(peer_rel_id, CHARM_KEY, {"sync-password": "mellon"})

    with (
        patch("workload.KafkaWorkload.start") as patched_start_snap_service,
        patch("core.cluster.ZooKeeper.zookeeper_connected", return_value=True),
    ):
        harness.charm.on.start.emit()

        patched_start_snap_service.assert_not_called()
        assert harness.charm.unit.status == Status.NO_BROKER_CREDS.value.status


def test_update_status_blocks_if_broker_not_active(harness: Harness, zk_data, passwords_data):
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)

    with (
        patch("workload.KafkaWorkload.active", return_value=True),
        patch("events.upgrade.KafkaUpgrade.idle", return_value=True),
        patch("core.cluster.ZooKeeper.broker_active", return_value=False) as patched_broker_active,
    ):
        harness.charm.on.update_status.emit()
        assert patched_broker_active.call_count == 1
        assert harness.charm.unit.status == Status.ZK_NOT_CONNECTED.value.status


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="machine health checks not used on K8s")
def test_update_status_blocks_if_machine_not_configured(harness: Harness, zk_data, passwords_data):
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)

    with (
        patch("health.KafkaHealth.machine_configured", side_effect=SnapError()),
        patch("charm.KafkaCharm.healthy", return_value=True),
        patch("core.cluster.ZooKeeper.broker_active", return_value=True),
        patch("events.upgrade.KafkaUpgrade.idle", return_value=True),
    ):
        harness.charm.on.update_status.emit()
        assert harness.charm.unit.status == Status.SNAP_NOT_RUNNING.value.status


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="sysctl config not used on K8s")
def test_update_status_sets_sysconf_warning(harness: Harness, zk_data, passwords_data):
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)

    with (
        patch("workload.KafkaWorkload.active", return_value=True),
        patch("core.cluster.ZooKeeper.broker_active", return_value=True),
        patch("health.KafkaHealth.machine_configured", return_value=False),
        patch("events.upgrade.KafkaUpgrade.idle", return_value=True),
    ):
        harness.charm.on.update_status.emit()
        assert harness.charm.unit.status == Status.SYSCONF_NOT_OPTIMAL.value.status


def test_update_status_sets_active(
    harness: Harness, zk_data, passwords_data, patched_health_machine_configured
):
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)

    with (
        patch("workload.KafkaWorkload.active", return_value=True),
        patch("core.cluster.ZooKeeper.broker_active", return_value=True),
        patch("events.upgrade.KafkaUpgrade.idle", return_value=True),
    ):
        harness.charm.on.update_status.emit()
        assert harness.charm.unit.status == Status.ACTIVE.value.status


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="multiple storage not supported in K8s")
def test_storage_add_does_nothing_if_snap_not_active(harness: Harness, zk_data, passwords_data):
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")
        harness.set_leader(True)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)

    with (
        patch("workload.KafkaWorkload.active", return_value=False),
        patch("charm.KafkaCharm._disable_enable_restart") as patched_restart,
    ):
        harness.add_storage(storage_name="data", count=2)
        harness.attach_storage(storage_id="data/1")

        assert patched_restart.call_count == 0


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="multiple storage not supported in K8s")
def test_storage_add_defers_if_service_not_healthy(harness: Harness, zk_data, passwords_data):
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")
        harness.set_leader(True)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)

    with (
        patch("workload.KafkaWorkload.active", return_value=True),
        patch("charm.KafkaCharm.healthy", return_value=False),
        patch("charm.KafkaCharm._disable_enable_restart") as patched_restart,
        patch("ops.framework.EventBase.defer") as patched_defer,
    ):
        harness.add_storage(storage_name="data", count=2)
        harness.attach_storage(storage_id="data/1")

        assert patched_restart.call_count == 0
        assert patched_defer.call_count == 1


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="multiple storage not supported in K8s")
def test_storage_add_disableenables_and_starts(harness: Harness, zk_data, passwords_data):
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")
        harness.set_leader(True)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.update_relation_data(zk_rel_id, ZK, zk_data)
        harness.update_relation_data(peer_rel_id, CHARM_KEY, passwords_data)

    with (
        patch("workload.KafkaWorkload.active", return_value=True),
        patch("charm.KafkaCharm.healthy", return_value=True),
        patch("events.upgrade.KafkaUpgrade.idle", return_value=True),
        patch("managers.config.KafkaConfigManager.set_server_properties"),
        patch("managers.config.KafkaConfigManager.set_client_properties"),
        patch("managers.config.KafkaConfigManager.set_environment"),
        patch("workload.KafkaWorkload.read", return_value=["gandalf=grey"]),
        patch("workload.KafkaWorkload.disable_enable") as patched_disable_enable,
        patch("workload.KafkaWorkload.start") as patched_start,
        patch("ops.framework.EventBase.defer") as patched_defer,
    ):
        harness.add_storage(storage_name="data", count=2)
        harness.attach_storage(storage_id="data/1")

        assert patched_disable_enable.call_count == 1
        assert patched_start.call_count == 1
        assert patched_defer.call_count == 0


def test_zookeeper_changed_sets_passwords_and_creates_users_with_zk(harness: Harness, zk_data):
    """Checks inter-broker passwords are created on zookeeper-changed hook using zk auth."""
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")
        harness.set_leader(True)
        zk_rel_id = harness.add_relation(ZK, ZK)

    with (
        patch("workload.KafkaWorkload.active", return_value=True),
        patch("managers.auth.AuthManager.add_user") as patched_add_user,
        patch("managers.config.KafkaConfigManager.set_zk_jaas_config") as patched_set_zk_jaas,
        patch(
            "managers.config.KafkaConfigManager.set_server_properties"
        ) as patched_set_server_properties,
    ):
        harness.update_relation_data(zk_rel_id, ZK, zk_data)

        for user in INTERNAL_USERS:
            assert harness.charm.state.cluster.relation_data.get(f"{user}-password", None)

        patched_set_zk_jaas.assert_called()
        patched_set_server_properties.assert_called()

        # checks all users are INTERNAL only
        for call in patched_add_user.kwargs.get("username", []):
            assert call in INTERNAL_USERS

        # checks all users added are added with --zookeeper auth
        for call in patched_add_user.kwargs.get("zk_auth", False):
            assert True


def test_zookeeper_joined_sets_chroot(harness: Harness):
    """Checks chroot is added to ZK relation data on ZKrelationjoined hook."""
    harness.add_relation(PEER, CHARM_KEY)
    harness.set_leader(True)
    zk_rel_id = harness.add_relation(ZK, ZK)
    harness.add_relation_unit(zk_rel_id, f"{ZK}/0")

    rel = harness.charm.model.relations[ZK][0].data[harness.charm.app]
    assert CHARM_KEY in rel.get("database", rel.get("chroot", ""))


def test_zookeeper_broken_stops_service_and_removes_meta_properties(harness: Harness):
    """Checks chroot is added to ZK relation data on ZKrelationjoined hook."""
    harness.add_relation(PEER, CHARM_KEY)
    zk_rel_id = harness.add_relation(ZK, ZK)

    with (
        patch("workload.KafkaWorkload.stop") as patched_stop_snap_service,
        patch("workload.KafkaWorkload.exec") as patched_exec,
    ):
        harness.remove_relation(zk_rel_id)

        patched_stop_snap_service.assert_called_once()
        assert re.match(r"rm .*/meta.properties", patched_exec.call_args_list[0].args[0])
        assert isinstance(harness.charm.unit.status, BlockedStatus)


def test_zookeeper_broken_cleans_internal_user_credentials(harness: Harness):
    """Checks chroot is added to ZK relation data on ZKrelationjoined hook."""
    with harness.hooks_disabled():
        harness.add_relation(PEER, CHARM_KEY)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.set_leader(True)

    with (
        patch("workload.KafkaWorkload.stop"),
        patch("workload.KafkaWorkload.exec"),
        patch("core.models.KafkaCluster.update") as patched_update,
        patch(
            "core.models.KafkaCluster.internal_user_credentials",
            new_callable=PropertyMock,
            return_value={"saruman": "orthanc"},
        ),
    ):
        harness.remove_relation(zk_rel_id)

        patched_update.assert_called_once_with({"saruman-password": ""})


def test_config_changed_updates_server_properties(harness: Harness, zk_data):
    """Checks that new charm/unit config writes server config to unit on config changed hook."""
    with harness.hooks_disabled():
        peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
        zk_rel_id = harness.add_relation(ZK, ZK)
        harness.add_relation_unit(zk_rel_id, f"{ZK}/0")
        harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")
        harness.update_relation_data(zk_rel_id, ZK, zk_data)

    with (
        patch(
            "managers.config.KafkaConfigManager.server_properties",
            new_callable=PropertyMock,
            return_value=["gandalf=white"],
        ),
        patch("charm.KafkaCharm.healthy", return_value=True),
        patch("events.upgrade.KafkaUpgrade.idle", return_value=True),
        patch("workload.KafkaWorkload.read", return_value=["gandalf=grey"]),
        patch("managers.config.KafkaConfigManager.set_server_properties") as set_server_properties,
        patch("managers.config.KafkaConfigManager.set_client_properties"),
    ):
        harness.charm.on.config_changed.emit()

        set_server_properties.assert_called_once()


def test_config_changed_updates_client_properties(harness: Harness):
    """Checks that new charm/unit config writes client config to unit on config changed hook."""
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")

    with (
        patch(
            "managers.config.KafkaConfigManager.client_properties",
            new_callable=PropertyMock,
            return_value=["gandalf=white"],
        ),
        patch(
            "managers.config.KafkaConfigManager.server_properties",
            new_callable=PropertyMock,
            return_value=["sauron=bad"],
        ),
        patch("charm.KafkaCharm.healthy", return_value=True),
        patch("events.upgrade.KafkaUpgrade.idle", return_value=True),
        patch("workload.KafkaWorkload.read", return_value=["gandalf=grey"]),
        patch("managers.config.KafkaConfigManager.set_server_properties"),
        patch("managers.config.KafkaConfigManager.set_client_properties") as set_client_properties,
    ):
        harness.charm.on.config_changed.emit()

        set_client_properties.assert_called_once()


def test_config_changed_updates_client_data(harness: Harness):
    """Checks that provided relation data updates on config changed hook."""
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")
    harness.add_relation(REL_NAME, "app")

    with (
        patch(
            "managers.config.KafkaConfigManager.server_properties",
            new_callable=PropertyMock,
            return_value=["gandalf=white"],
        ),
        patch("charm.KafkaCharm.healthy", return_value=True),
        patch("events.upgrade.KafkaUpgrade.idle", return_value=True),
        patch("workload.KafkaWorkload.read", return_value=["gandalf=white"]),
        patch("managers.config.KafkaConfigManager.set_zk_jaas_config"),
        patch("charm.KafkaCharm.update_client_data") as patched_update_client_data,
        patch(
            "managers.config.KafkaConfigManager.set_client_properties"
        ) as patched_set_client_properties,
    ):
        harness.set_leader(True)
        harness.charm.on.config_changed.emit()

        patched_set_client_properties.assert_called_once()
        patched_update_client_data.assert_called_once()


def test_config_changed_restarts(harness: Harness):
    """Checks units rolling-restat on config changed hook."""
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")
    harness.set_leader(True)
    zk_rel_id = harness.add_relation(ZK, ZK)
    harness.add_relation_unit(zk_rel_id, f"{ZK}/0")

    with (
        patch(
            "managers.config.KafkaConfigManager.server_properties",
            new_callable=PropertyMock,
            return_value=["gandalf=grey"],
        ),
        patch("charm.KafkaCharm.healthy", return_value=True),
        patch("workload.KafkaWorkload.read", return_value=["gandalf=white"]),
        patch("events.upgrade.KafkaUpgrade.idle", return_value=True),
        patch("workload.KafkaWorkload.restart") as patched_restart_snap_service,
        patch("core.cluster.ZooKeeper.broker_active", return_value=True),
        patch("core.cluster.ZooKeeper.zookeeper_connected", return_value=True),
        patch("managers.auth.AuthManager.add_user"),
        patch("managers.config.KafkaConfigManager.set_zk_jaas_config"),
        patch("managers.config.KafkaConfigManager.set_server_properties"),
    ):
        harness.update_relation_data(zk_rel_id, ZK, {"username": "glorfindel"})
        patched_restart_snap_service.reset_mock()

        harness.charm.on.config_changed.emit()
        patched_restart_snap_service.assert_called_once()


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="sysctl config not used on K8s")
def test_on_remove_sysctl_is_deleted(harness: Harness):
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")

    with patch("charm.sysctl.Config.remove") as patched_sysctl_remove:
        harness.charm.on.remove.emit()

        patched_sysctl_remove.assert_called_once()


def test_workload_version_is_setted(harness, monkeypatch):
    output_install = "3.6.0-ubuntu0"
    output_changed = "3.6.1-ubuntu0"
    monkeypatch.setattr(
        harness.charm.workload,
        "run_bin_command",
        Mock(side_effect=[output_install, output_changed]),
    )
    monkeypatch.setattr(harness.charm.workload, "install", Mock(return_value=True))

    harness.charm.on.install.emit()
    assert harness.get_workload_version() == "3.6.0"

    with (
        patch(
            "managers.config.KafkaConfigManager.server_properties",
            new_callable=PropertyMock,
            return_value=["gandalf=grey"],
        ),
        patch("charm.KafkaCharm.healthy", return_value=True),
        patch("workload.KafkaWorkload.read", return_value=["gandalf=white"]),
        patch("events.upgrade.KafkaUpgrade.idle", return_value=True),
    ):

        harness.charm.on.config_changed.emit()

    assert harness.get_workload_version() == "3.6.1"
