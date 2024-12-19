#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
import logging
import re
from pathlib import Path
from typing import cast
from unittest.mock import PropertyMock, patch

import pytest
import yaml
from ops.testing import Container, Context, PeerRelation, Relation, State, Storage

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

pytestmark = pytest.mark.broker


logger = logging.getLogger(__name__)


CONFIG = yaml.safe_load(Path("./config.yaml").read_text())
ACTIONS = yaml.safe_load(Path("./actions.yaml").read_text())
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())


@pytest.fixture()
def base_state():
    if SUBSTRATE == "k8s":
        state = State(leader=True, containers=[Container(name=CONTAINER, can_connect=True)])

    else:
        state = State(leader=True)

    return state


@pytest.fixture()
def ctx() -> Context:
    ctx = Context(KafkaCharm, meta=METADATA, config=CONFIG, actions=ACTIONS, unit_id=0)
    return ctx


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="sysctl config not used on K8s")
def test_install_blocks_snap_install_failure(ctx: Context, base_state: State) -> None:
    """Checks unit goes to BlockedStatus after snap failure on install hook."""
    # Given
    state_in = base_state

    # When
    with patch("workload.Workload.install", return_value=False), patch("workload.Workload.write"):
        state_out = ctx.run(ctx.on.install(), state_in)

    # Then
    assert state_out.unit_status == Status.SNAP_NOT_INSTALLED.value.status


def test_install_sets_env_vars(ctx: Context, base_state: State, patched_etc_environment) -> None:
    """Checks KAFKA_OPTS and other vars are written to /etc/environment on install hook."""
    # Given
    state_in = base_state

    # When
    with patch("workload.Workload.install"):
        _ = ctx.run(ctx.on.install(), state_in)

    # Then
    patched_etc_environment.assert_called_once()


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="sysctl config not used on K8s")
def test_install_configures_os(ctx: Context, base_state: State, patched_sysctl_config) -> None:
    # Given
    state_in = base_state

    # When
    with patch("workload.Workload.install"):
        _ = ctx.run(ctx.on.install(), state_in)

    # Then
    patched_sysctl_config.assert_called_once_with(OS_REQUIREMENTS)


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="sysctl config not used on K8s")
def test_install_sets_status_if_os_config_fails(
    ctx: Context, base_state: State, patched_sysctl_config
) -> None:
    # Given
    state_in = base_state

    # When
    with patch("workload.Workload.install"):
        patched_sysctl_config.side_effect = ApplyError("Error setting values")
        state_out = ctx.run(ctx.on.install(), state_in)

    # Then
    assert state_out.unit_status == Status.SYSCONF_NOT_POSSIBLE.value.status


def test_ready_to_start_maintenance_no_peer_relation(ctx: Context, base_state: State) -> None:
    # Given
    state_in = base_state

    # When
    state_out = ctx.run(ctx.on.start(), state_in)

    # Then
    assert state_out.unit_status == Status.NO_PEER_RELATION.value.status


def test_ready_to_start_blocks_no_zookeeper_relation(ctx: Context, base_state: State) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer])

    # When
    state_out = ctx.run(ctx.on.start(), state_in)

    # Then
    assert state_out.unit_status == Status.MISSING_MODE.value.status


def test_ready_to_start_waits_no_zookeeper_data(ctx: Context, base_state: State) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    zk_relation = Relation(ZK, ZK)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, zk_relation])

    # When
    state_out = ctx.run(ctx.on.start(), state_in)

    # Then
    assert state_out.unit_status == Status.ZK_NO_DATA.value.status


def test_ready_to_start_waits_no_user_credentials(
    ctx: Context, base_state: State, zk_data: dict[str, str]
) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, zk_relation])

    # When
    state_out = ctx.run(ctx.on.start(), state_in)

    # Then
    assert state_out.unit_status == Status.NO_BROKER_CREDS.value.status


def test_ready_to_start_blocks_mismatch_tls(
    ctx: Context, base_state: State, zk_data: dict[str, str], passwords_data: dict[str, str]
) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data | {"tls": "enabled"})
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, zk_relation])

    # When
    state_out = ctx.run(ctx.on.start(), state_in)

    # Then
    assert state_out.unit_status == Status.ZK_TLS_MISMATCH.value.status


def test_ready_to_start_succeeds(
    ctx: Context, base_state: State, zk_data: dict[str, str], passwords_data: dict[str, str]
) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data)
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, zk_relation])

    # When
    with (
        patch("workload.KafkaWorkload.active", return_value=True),
        patch("workload.KafkaWorkload.write"),
        patch("workload.KafkaWorkload.start") as patched_start,
        patch("events.broker.BrokerOperator._on_update_status", autospec=True),
    ):
        ctx.run(ctx.on.start(), state_in)

    # Then
    assert patched_start.call_count


def test_healthy_fails_if_not_ready_to_start(
    ctx: Context, base_state: State, zk_data: dict[str, str], passwords_data: dict[str, str]
) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data | {"tls": "enabled"})
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, zk_relation])

    # When
    with ctx(ctx.on.start(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)
        assert not charm.broker.healthy


def test_healthy_fails_if_snap_not_active(
    ctx: Context, base_state: State, zk_data: dict[str, str], passwords_data: dict[str, str]
) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data)
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, zk_relation])

    # When
    with (
        patch("workload.KafkaWorkload.active", return_value=False) as patched_snap_active,
        patch("workload.KafkaWorkload.start"),
        ctx(ctx.on.start(), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)
        assert not charm.broker.healthy
        state_out = manager.run()

    # Then
    assert patched_snap_active.call_count
    assert state_out.unit_status == Status.BROKER_NOT_RUNNING.value.status


def test_healthy_succeeds(
    ctx: Context, base_state: State, zk_data: dict[str, str], passwords_data: dict[str, str]
):
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data)
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, zk_relation])

    with (
        patch("workload.KafkaWorkload.active", return_value=True),
        ctx(ctx.on.collect_app_status(), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)
        assert charm.broker.healthy


def test_start_defers_without_zookeeper(ctx: Context, base_state: State) -> None:
    """Checks event deferred and not lost without ZK relation on start hook."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer])

    # When
    state_out = ctx.run(ctx.on.start(), state_in)

    # Then
    assert len(state_out.deferred) == 2
    assert state_out.deferred[0].name == "start"


def test_start_sets_necessary_config(
    ctx: Context, base_state: State, zk_data: dict[str, str], passwords_data: dict[str, str]
) -> None:
    """Checks event writes all needed config to unit on start hook."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data)
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, zk_relation])

    # When
    with (
        # NOTE: Patching `active` cuts the hook short, as we are only testing properties being set.
        patch("workload.KafkaWorkload.active", return_value=False),
        patch("managers.auth.AuthManager.add_user"),
        patch("managers.config.ConfigManager.set_zk_jaas_config") as patched_jaas,
        patch("managers.config.ConfigManager.set_server_properties") as patched_server_properties,
        patch("managers.config.ConfigManager.set_client_properties") as patched_client_properties,
        patch("workload.KafkaWorkload.start"),
    ):
        ctx.run(ctx.on.start(), state_in)

    # Then
    patched_jaas.assert_called_once()
    patched_server_properties.assert_called_once()
    patched_client_properties.assert_called_once()


@pytest.mark.skipif(SUBSTRATE == "vm", reason="pebble layer not used on vm")
def test_start_sets_pebble_layer(
    ctx: Context, base_state: State, zk_data: dict[str, str], passwords_data: dict[str, str]
) -> None:
    """Checks layer is the expected at start."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data)
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, zk_relation])

    # When
    with (
        # NOTE: Patching `active` cuts the hook short, as we are only testing layer being set.
        patch("workload.KafkaWorkload.active", return_value=False),
        patch("managers.auth.AuthManager.add_user"),
        patch("managers.config.ConfigManager.set_zk_jaas_config"),
        patch("managers.config.ConfigManager.set_server_properties"),
        patch("managers.config.ConfigManager.set_client_properties"),
        patch("workload.KafkaWorkload.start"),
        ctx(ctx.on.start(), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)
        extra_opts = [
            f"-javaagent:{charm.workload.paths.jmx_prometheus_javaagent}={JMX_EXPORTER_PORT}:{charm.workload.paths.jmx_prometheus_config}",
            f"-Djava.security.auth.login.config={charm.workload.paths.zk_jaas}",
        ]
        command = f"{charm.workload.paths.binaries_path}/bin/kafka-server-start.sh {charm.workload.paths.server_properties}"
        expected_plan = {
            "description": "Pebble config layer for kafka",
            "services": {
                CONTAINER: {
                    "override": "merge",
                    "summary": "kafka",
                    "command": command,
                    "startup": "enabled",
                    "user": "kafka",
                    "group": "kafka",
                    "environment": {
                        "KAFKA_OPTS": " ".join(extra_opts),
                        "JAVA_HOME": "/usr/lib/jvm/java-18-openjdk-amd64",
                        "LOG_DIR": charm.workload.paths.logs_path,
                    },
                },
            },
            "summary": "kafka layer",
        }
        found_plan = charm.broker.workload.layer.to_dict()

    # Then
    assert expected_plan == found_plan


def test_start_does_not_start_if_not_ready(ctx: Context, base_state: State) -> None:
    """Checks snap service does not start before ready on start hook."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer])

    # When
    with (
        patch("workload.KafkaWorkload.start") as patched_start_snap_service,
        patch("ops.framework.EventBase.defer") as patched_defer,
    ):
        _ = ctx.run(ctx.on.start(), state_in)

    # Then
    patched_start_snap_service.assert_not_called()
    patched_defer.assert_called()


def test_start_does_not_start_if_not_same_tls_as_zk(ctx: Context, base_state: State):
    """Checks snap service does not start if mismatch Kafka+ZK TLS on start hook."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    zk_relation = Relation(ZK, ZK)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, zk_relation])

    # When
    with (
        patch("managers.auth.AuthManager.add_user"),
        patch("workload.KafkaWorkload.start") as patched_start_snap_service,
        patch("core.cluster.ZooKeeper.zookeeper_connected", return_value=True),
        patch("core.models.KafkaCluster.internal_user_credentials", return_value="orthanc"),
        patch("core.models.KafkaCluster.tls_enabled", return_value=True),
    ):
        state_out = ctx.run(ctx.on.start(), state_in)

    # Then
    patched_start_snap_service.assert_not_called()
    assert state_out.unit_status == Status.ZK_TLS_MISMATCH.value.status


def test_start_does_not_start_if_leader_has_not_set_creds(ctx: Context, base_state: State) -> None:
    """Checks snap service does not start without inter-broker creds on start hook."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data={"sync-password": "mellon"})
    zk_relation = Relation(ZK, ZK)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, zk_relation])

    # When
    with (
        patch("workload.KafkaWorkload.start") as patched_start_snap_service,
        patch("core.cluster.ZooKeeper.zookeeper_connected", return_value=True),
    ):
        state_out = ctx.run(ctx.on.start(), state_in)

    # Then
    patched_start_snap_service.assert_not_called()
    assert state_out.unit_status == Status.NO_BROKER_CREDS.value.status


def test_update_status_blocks_if_broker_not_active(
    ctx: Context, base_state: State, zk_data: dict[str, str], passwords_data: dict[str, str]
):
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data)
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, zk_relation])

    # When
    with (
        patch("workload.KafkaWorkload.active", return_value=True),
        patch("events.upgrade.KafkaUpgrade.idle", return_value=True),
        patch("core.cluster.ZooKeeper.broker_active", return_value=False) as patched_broker_active,
    ):
        state_out = ctx.run(ctx.on.update_status(), state_in)

    # Then
    assert patched_broker_active.call_count == 1
    assert state_out.unit_status == Status.ZK_NOT_CONNECTED.value.status


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="machine health checks not used on K8s")
def test_update_status_blocks_if_machine_not_configured(
    ctx: Context, base_state: State, zk_data: dict[str, str], passwords_data: dict[str, str]
) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data)
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, zk_relation])

    # When

    with (
        patch("health.KafkaHealth.machine_configured", side_effect=SnapError()),
        patch("events.broker.BrokerOperator.healthy", return_value=True),
        patch("core.cluster.ZooKeeper.broker_active", return_value=True),
        patch("events.upgrade.KafkaUpgrade.idle", return_value=True),
    ):
        state_out = ctx.run(ctx.on.update_status(), state_in)

    # Then
    assert state_out.unit_status == Status.BROKER_NOT_RUNNING.value.status


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="sysctl config not used on K8s")
def test_update_status_sets_sysconf_warning(
    ctx: Context, base_state: State, zk_data: dict[str, str], passwords_data: dict[str, str]
) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data)
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, zk_relation])

    # When
    with (
        patch("workload.KafkaWorkload.active", return_value=True),
        patch("core.cluster.ZooKeeper.broker_active", return_value=True),
        patch("health.KafkaHealth.machine_configured", return_value=False),
        patch("events.upgrade.KafkaUpgrade.idle", return_value=True),
    ):
        state_out = ctx.run(ctx.on.update_status(), state_in)

    # Then
    assert state_out.unit_status == Status.SYSCONF_NOT_OPTIMAL.value.status


def test_update_status_sets_active(
    ctx: Context,
    base_state: State,
    zk_data: dict[str, str],
    passwords_data: dict[str, str],
    patched_health_machine_configured,
) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data)
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, zk_relation])

    # When
    with (
        patch("workload.KafkaWorkload.active", return_value=True),
        patch("core.cluster.ZooKeeper.broker_active", return_value=True),
        patch("events.upgrade.KafkaUpgrade.idle", return_value=True),
    ):
        state_out = ctx.run(ctx.on.update_status(), state_in)

    # Then
    assert state_out.unit_status == Status.ACTIVE.value.status


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="multiple storage not supported in K8s")
def test_storage_add_does_nothing_if_snap_not_active(
    ctx: Context, base_state: State, zk_data: dict[str, str], passwords_data: dict[str, str]
) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data)
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data)
    storage = Storage("data")
    state_in = dataclasses.replace(
        base_state, relations=[cluster_peer, zk_relation], storages=[storage]
    )

    # When
    with (
        patch("workload.KafkaWorkload.active", return_value=False),
        patch("charm.KafkaCharm._disable_enable_restart_broker") as patched_restart,
    ):
        ctx.run(ctx.on.storage_attached(storage), state_in)

    # Then
    assert patched_restart.call_count == 0


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="multiple storage not supported in K8s")
def test_storage_add_defers_if_service_not_healthy(
    ctx: Context, base_state: State, zk_data: dict[str, str], passwords_data: dict[str, str]
) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data)
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data)
    storage = Storage("data")
    state_in = dataclasses.replace(
        base_state, relations=[cluster_peer, zk_relation], storages=[storage]
    )

    # When
    with (
        patch("workload.KafkaWorkload.active", return_value=True),
        patch("events.broker.BrokerOperator.healthy", return_value=False),
        patch("charm.KafkaCharm._disable_enable_restart_broker") as patched_restart,
        patch("ops.framework.EventBase.defer") as patched_defer,
    ):
        ctx.run(ctx.on.storage_attached(storage), state_in)

    # Then
    assert patched_restart.call_count == 0
    assert patched_defer.call_count == 1


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="multiple storage not supported in K8s")
def test_storage_add_disableenables_and_starts(
    ctx: Context, base_state: State, zk_data: dict[str, str], passwords_data: dict[str, str]
) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data)
    restart_peer = PeerRelation("restart", "restart")
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data)
    storage = Storage("data")
    state_in = dataclasses.replace(
        base_state, relations=[cluster_peer, restart_peer, zk_relation], storages=[storage]
    )

    # When
    with (
        patch("workload.KafkaWorkload.active", return_value=True),
        patch("events.broker.BrokerOperator.healthy", return_value=True),
        patch("events.upgrade.KafkaUpgrade.idle", return_value=True),
        patch("managers.config.ConfigManager.set_server_properties"),
        patch("managers.config.ConfigManager.set_client_properties"),
        patch("managers.config.ConfigManager.set_environment"),
        patch("workload.KafkaWorkload.read", return_value=["gandalf=grey"]),
        patch("workload.KafkaWorkload.disable_enable") as patched_disable_enable,
        patch("workload.KafkaWorkload.start") as patched_start,
        patch("ops.framework.EventBase.defer") as patched_defer,
    ):
        ctx.run(ctx.on.storage_attached(storage), state_in)

    # Then
    assert patched_disable_enable.call_count == 1
    assert patched_start.call_count == 1
    assert patched_defer.call_count == 0


def test_zookeeper_changed_sets_passwords_and_creates_users_with_zk(
    ctx: Context, base_state: State, zk_data: dict[str, str]
) -> None:
    """Checks inter-broker passwords are created on zookeeper-changed hook using zk auth."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data)
    state_in = dataclasses.replace(
        base_state,
        relations=[cluster_peer, zk_relation],
    )

    # When
    with (
        patch("workload.KafkaWorkload.active", return_value=True),
        patch("managers.auth.AuthManager.add_user") as patched_add_user,
        patch("managers.config.ConfigManager.set_zk_jaas_config") as patched_set_zk_jaas,
        patch(
            "managers.config.ConfigManager.set_server_properties"
        ) as patched_set_server_properties,
        ctx(ctx.on.relation_changed(zk_relation), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)
        manager.run()
        for user in INTERNAL_USERS:
            assert charm.state.cluster.relation_data.get(f"{user}-password", None)

    # Then
    patched_set_zk_jaas.assert_called()
    patched_set_server_properties.assert_called()

    # checks all users are INTERNAL only
    for call in patched_add_user.kwargs.get("username", []):
        assert call in INTERNAL_USERS

    # checks all users added are added with --zookeeper auth
    for call in patched_add_user.kwargs.get("zk_auth", False):
        assert True


def test_zookeeper_created_sets_chroot(ctx: Context, base_state: State) -> None:
    """Checks chroot is added to ZK relation data on ZKrelationcreated hook."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    zk_relation = Relation(ZK, ZK)
    state_in = dataclasses.replace(
        base_state,
        relations=[cluster_peer, zk_relation],
    )

    # When
    state_out = ctx.run(ctx.on.relation_created(zk_relation), state_in)

    # Then
    assert (local_databag := state_out.get_relation(zk_relation.id).local_app_data)
    assert CHARM_KEY in local_databag.get("database", "")


def test_zookeeper_broken_stops_service_and_removes_meta_properties(
    ctx: Context, base_state: State
) -> None:
    """Checks chroot is added to ZK relation data on ZKrelationjoined hook."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    zk_relation = Relation(ZK, ZK)
    state_in = dataclasses.replace(
        base_state,
        relations=[cluster_peer, zk_relation],
    )

    # When
    with (
        patch("workload.KafkaWorkload.stop") as patched_stop_snap_service,
        patch("workload.KafkaWorkload.exec") as patched_exec,
    ):
        state_out = ctx.run(ctx.on.relation_broken(zk_relation), state_in)

    # Then
    patched_stop_snap_service.assert_called_once()
    assert re.findall(r"meta.properties -delete", " ".join(patched_exec.call_args_list[1].args[0]))
    assert state_out.unit_status == Status.ZK_NOT_RELATED.value.status


def test_zookeeper_broken_cleans_internal_user_credentials(
    ctx: Context, base_state: State
) -> None:
    """Checks chroot is added to ZK relation data on ZKrelationjoined hook."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    zk_relation = Relation(ZK, ZK)
    state_in = dataclasses.replace(
        base_state,
        relations=[cluster_peer, zk_relation],
    )

    # When
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
        ctx.run(ctx.on.relation_broken(zk_relation), state_in)

    # Then
    patched_update.assert_called_once_with({"saruman-password": ""})


def test_config_changed_updates_server_properties(
    ctx: Context, base_state: State, zk_data: dict[str, str]
) -> None:
    """Checks that new charm/unit config writes server config to unit on config changed hook."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    restart_peer = PeerRelation("restart", "rolling_op")
    zk_relation = Relation(ZK, ZK, remote_app_data=zk_data)
    state_in = dataclasses.replace(
        base_state,
        relations=[cluster_peer, restart_peer, zk_relation],
    )

    # When
    with (
        patch(
            "managers.config.ConfigManager.server_properties",
            new_callable=PropertyMock,
            return_value=["gandalf=white"],
        ),
        patch("events.broker.BrokerOperator.healthy", return_value=True),
        patch("events.upgrade.KafkaUpgrade.idle", return_value=True),
        patch("workload.KafkaWorkload.read", return_value=["gandalf=grey"]),
        patch("managers.config.ConfigManager.set_server_properties") as set_server_properties,
        patch("managers.config.ConfigManager.set_client_properties"),
        patch(
            "charms.rolling_ops.v0.rollingops.RollingOpsManager._on_run_with_lock", autospec=True
        ),
    ):
        ctx.run(ctx.on.config_changed(), state_in)

    # Then
    set_server_properties.assert_called_once()


def test_config_changed_updates_client_properties(ctx: Context, base_state: State) -> None:
    """Checks that new charm/unit config writes client config to unit on config changed hook."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    restart_peer = PeerRelation("restart", "rolling_op")
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, restart_peer])

    # When
    with (
        patch(
            "managers.config.ConfigManager.client_properties",
            new_callable=PropertyMock,
            return_value=["gandalf=white"],
        ),
        patch(
            "managers.config.ConfigManager.server_properties",
            new_callable=PropertyMock,
            return_value=["sauron=bad"],
        ),
        patch("events.broker.BrokerOperator.healthy", return_value=True),
        patch("events.upgrade.KafkaUpgrade.idle", return_value=True),
        patch("workload.KafkaWorkload.read", return_value=["gandalf=grey"]),
        patch("managers.config.ConfigManager.set_server_properties"),
        patch("managers.config.ConfigManager.set_client_properties") as set_client_properties,
        patch(
            "charms.rolling_ops.v0.rollingops.RollingOpsManager._on_run_with_lock", autospec=True
        ),
    ):
        ctx.run(ctx.on.config_changed(), state_in)

    # Then
    set_client_properties.assert_called_once()


def test_config_changed_updates_client_data(ctx: Context, base_state: State) -> None:
    """Checks that provided relation data updates on config changed hook."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    restart_peer = PeerRelation("restart", "rolling_op")
    client = Relation(REL_NAME, REL_NAME)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, restart_peer, client])

    # When
    with (
        patch(
            "managers.config.ConfigManager.server_properties",
            new_callable=PropertyMock,
            return_value=["gandalf=white"],
        ),
        patch("events.broker.BrokerOperator.healthy", return_value=True),
        patch("events.upgrade.KafkaUpgrade.idle", return_value=True),
        patch("workload.KafkaWorkload.read", return_value=["gandalf=white"]),
        patch("managers.config.ConfigManager.set_zk_jaas_config"),
        patch("events.broker.BrokerOperator.update_client_data") as patched_update_client_data,
        patch(
            "managers.config.ConfigManager.set_client_properties"
        ) as patched_set_client_properties,
        patch(
            "charms.rolling_ops.v0.rollingops.RollingOpsManager._on_run_with_lock", autospec=True
        ),
    ):
        ctx.run(ctx.on.config_changed(), state_in)

    # Then
    patched_set_client_properties.assert_called_once()
    patched_update_client_data.assert_called_once()


def test_config_changed_restarts(ctx: Context, base_state: State) -> None:
    """Checks units rolling-restat on config changed hook."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    restart_peer = PeerRelation("restart", "rolling_op")
    zk_relation = Relation(ZK, ZK, remote_app_data={"username": "glorfindel"})
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, restart_peer, zk_relation])

    with (
        patch(
            "managers.config.ConfigManager.server_properties",
            new_callable=PropertyMock,
            return_value=["gandalf=grey"],
        ),
        patch("events.broker.BrokerOperator.healthy", return_value=True),
        patch("workload.KafkaWorkload.read", return_value=["gandalf=white"]),
        patch("events.upgrade.KafkaUpgrade.idle", return_value=True),
        patch("core.cluster.ZooKeeper.broker_active", return_value=True),
        patch("core.cluster.ZooKeeper.zookeeper_connected", return_value=True),
        patch("managers.auth.AuthManager.add_user"),
        patch("managers.config.ConfigManager.set_zk_jaas_config"),
        patch("managers.config.ConfigManager.set_server_properties"),
        patch(
            "charms.rolling_ops.v0.rollingops.RollingOpsManager._on_run_with_lock", autospec=True
        ) as patched_restart_lib,
    ):

        ctx.run(ctx.on.config_changed(), state_in)
        patched_restart_lib.assert_called_once()
        pass


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="sysctl config not used on K8s")
def test_on_remove_sysctl_is_deleted(ctx: Context, base_state: State):
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer])

    # When
    with patch("charm.sysctl.Config.remove") as patched_sysctl_remove:
        ctx.run(ctx.on.remove(), state_in)

    # Then
    patched_sysctl_remove.assert_called_once()


def test_workload_version_is_setted(ctx: Context, base_state: State):
    # Given
    output_bin_install = "3.6.0-ubuntu0"
    output_bin_changed = "3.6.1-ubuntu0"
    expected_version_installed = "3.6.0"
    expected_version_changed = "3.6.1"
    restart_peer = PeerRelation("restart", "rolling_op")
    state_in = dataclasses.replace(base_state, relations=[restart_peer])

    # When
    with (
        patch(
            "managers.config.ConfigManager.server_properties",
            new_callable=PropertyMock,
            return_value=["gandalf=grey"],
        ),
        patch("events.broker.BrokerOperator.healthy", return_value=True),
        patch("workload.KafkaWorkload.read", return_value=["gandalf=white"]),
        patch("workload.KafkaWorkload.install", return_value=True),
        patch(
            "workload.KafkaWorkload.run_bin_command",
            side_effect=[output_bin_install, output_bin_changed],
        ),
        patch("events.upgrade.KafkaUpgrade.idle", return_value=True),
        patch(
            "charms.rolling_ops.v0.rollingops.RollingOpsManager._on_run_with_lock", autospec=True
        ),
    ):
        state_intermediary = ctx.run(ctx.on.install(), state_in)
        state_out = ctx.run(ctx.on.config_changed(), state_intermediary)

    # Then
    assert ctx.workload_version_history == [expected_version_installed]
    assert state_out.workload_version == expected_version_changed
