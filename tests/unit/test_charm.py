#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
import logging
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
    JMX_EXPORTER_PORT,
    PEER,
    REL_NAME,
    SUBSTRATE,
    Status,
)

if SUBSTRATE == "vm":
    from charms.operator_libs_linux.v0.sysctl import ApplyError
    from charms.operator_libs_linux.v2.snap import SnapError

    from literals import OS_REQUIREMENTS

pytestmark = pytest.mark.broker


logger = logging.getLogger(__name__)


CONFIG = yaml.safe_load(Path("./config.yaml").read_text())
ACTIONS = yaml.safe_load(Path("./actions.yaml").read_text())
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())


@pytest.fixture()
def base_state():
    config = {"roles": "broker,controller"}

    if SUBSTRATE == "k8s":
        state = State(
            leader=True, containers=[Container(name=CONTAINER, can_connect=True)], config=config
        )

    else:
        state = State(leader=True, config=config)

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


def test_ready_to_start_blocks_no_controller_relation(ctx: Context, base_state: State) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    state_in = dataclasses.replace(
        base_state, relations=[cluster_peer], config={"roles": "broker"}
    )

    # When
    state_out = ctx.run(ctx.on.start(), state_in)

    # Then
    assert state_out.unit_status == Status.MISSING_MODE.value.status


def test_ready_to_start_waits_no_broker_data(
    ctx: Context, base_state: State, peer_cluster_rel: Relation
) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    state_in = dataclasses.replace(
        base_state, relations=[cluster_peer, peer_cluster_rel], config={"roles": "controller"}
    )

    # When
    state_out = ctx.run(ctx.on.start(), state_in)

    # Then
    assert state_out.unit_status == Status.NO_BROKER_DATA.value.status


def test_ready_to_start_succeeds(
    ctx: Context, base_state: State, passwords_data: dict[str, str]
) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer])

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
    ctx: Context, base_state: State, passwords_data: dict[str, str]
) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data | {"tls": "enabled"})
    state_in = dataclasses.replace(base_state, relations=[cluster_peer])

    # When
    with ctx(ctx.on.start(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)
        assert not charm.broker.healthy


def test_healthy_fails_if_snap_not_active(
    ctx: Context, base_state: State, passwords_data: dict[str, str]
) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer])

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
    assert state_out.unit_status == Status.SERVICE_NOT_RUNNING.value.status


def test_healthy_succeeds(ctx: Context, base_state: State, passwords_data: dict[str, str]):
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer])

    with (
        patch("workload.KafkaWorkload.active", return_value=True),
        ctx(ctx.on.start(), state_in) as manager,
    ):
        charm = cast(KafkaCharm, manager.charm)
        _ = manager.run()
        assert charm.broker.healthy


def test_start_sets_necessary_config(
    ctx: Context, base_state: State, passwords_data: dict[str, str]
) -> None:
    """Checks event writes all needed config to unit on start hook."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer])

    # When
    with (
        # NOTE: Patching `active` cuts the hook short, as we are only testing properties being set.
        patch("workload.KafkaWorkload.active", return_value=False),
        patch("managers.auth.AuthManager.add_user"),
        patch("managers.config.ConfigManager.set_server_properties") as patched_server_properties,
        patch("managers.config.ConfigManager.set_client_properties") as patched_client_properties,
        patch("workload.KafkaWorkload.start"),
    ):
        ctx.run(ctx.on.start(), state_in)

    # Then
    patched_server_properties.assert_called()
    patched_client_properties.assert_called()


@pytest.mark.skipif(SUBSTRATE == "vm", reason="pebble layer not used on vm")
def test_start_sets_pebble_layer(
    ctx: Context, base_state: State, zk_data: dict[str, str], passwords_data: dict[str, str]
) -> None:
    """Checks layer is the expected at start."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer])

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
    state_in = dataclasses.replace(
        base_state, relations=[cluster_peer], config={"roles": "controller"}
    )

    # When
    with (
        patch("workload.KafkaWorkload.start") as patched_start_snap_service,
        patch("ops.framework.EventBase.defer") as patched_defer,
    ):
        _ = ctx.run(ctx.on.start(), state_in)

    # Then
    patched_start_snap_service.assert_not_called()
    patched_defer.assert_called()


def test_start_does_not_start_if_leader_has_not_set_creds(ctx: Context, base_state: State) -> None:
    """Checks snap service does not start without inter-broker creds on start hook."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data={"sync-password": "mellon"})
    state_in = dataclasses.replace(base_state, relations=[cluster_peer], leader=False)

    # When
    with (patch("workload.KafkaWorkload.start") as patched_start_snap_service,):
        state_out = ctx.run(ctx.on.start(), state_in)

    # Then
    patched_start_snap_service.assert_not_called()
    assert state_out.unit_status == Status.NO_BOOTSTRAP_CONTROLLER.value.status


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="machine health checks not used on K8s")
def test_update_status_blocks_if_machine_not_configured(
    ctx: Context, base_state: State, passwords_data: dict[str, str]
) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer])

    # When

    with (
        patch("health.KafkaHealth.machine_configured", side_effect=SnapError()),
        patch("events.broker.BrokerOperator.healthy", return_value=True),
        patch("events.upgrade.KafkaUpgrade.idle", return_value=True),
    ):
        state_out = ctx.run(ctx.on.update_status(), state_in)

    # Then
    assert state_out.unit_status == Status.SERVICE_NOT_RUNNING.value.status


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="sysctl config not used on K8s")
def test_update_status_sets_sysconf_warning(
    ctx: Context, base_state: State, passwords_data: dict[str, str], kraft_data: dict[str, str]
) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data | kraft_data)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer])

    # When
    with (
        patch("workload.KafkaWorkload.active", return_value=True),
        patch("health.KafkaHealth.machine_configured", return_value=False),
        patch("events.upgrade.KafkaUpgrade.idle", return_value=True),
    ):
        state_out = ctx.run(ctx.on.update_status(), state_in)

    # Then
    assert state_out.unit_status == Status.SYSCONF_NOT_OPTIMAL.value.status


def test_update_status_sets_active(
    ctx: Context,
    base_state: State,
    passwords_data: dict[str, str],
    kraft_data: dict[str, str],
    patched_health_machine_configured,
) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data | kraft_data)
    state_in = dataclasses.replace(base_state, relations=[cluster_peer])

    # When
    with (
        patch("workload.KafkaWorkload.active", return_value=True),
        patch("events.upgrade.KafkaUpgrade.idle", return_value=True),
    ):
        state_out = ctx.run(ctx.on.update_status(), state_in)

    # Then
    assert state_out.unit_status == Status.ACTIVE.value.status


@pytest.mark.skipif(SUBSTRATE == "k8s", reason="multiple storage not supported in K8s")
def test_storage_add_does_nothing_if_snap_not_active(
    ctx: Context, base_state: State, passwords_data: dict[str, str]
) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data)
    storage = Storage("data")
    state_in = dataclasses.replace(base_state, relations=[cluster_peer], storages=[storage])

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
    ctx: Context, base_state: State, kraft_data: dict[str, str], passwords_data: dict[str, str]
) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data | kraft_data)
    storage = Storage("data")
    state_in = dataclasses.replace(base_state, relations=[cluster_peer], storages=[storage])

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
def test_storage_add(
    ctx: Context, base_state: State, kraft_data: dict[str, str], passwords_data: dict[str, str]
) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER, local_app_data=passwords_data | kraft_data)
    restart_peer = PeerRelation("restart", "restart")
    storage = Storage("data")
    state_in = dataclasses.replace(
        base_state, relations=[cluster_peer, restart_peer], storages=[storage]
    )

    # When
    with (
        patch("workload.KafkaWorkload.active", return_value=True),
        patch("events.broker.BrokerOperator.healthy", return_value=True),
        patch("events.upgrade.KafkaUpgrade.idle", return_value=True),
        patch("managers.config.ConfigManager.set_server_properties"),
        patch("managers.config.ConfigManager.set_client_properties"),
        patch("managers.config.ConfigManager.set_environment"),
        patch("managers.controller.ControllerManager.format_storages") as patched_format_storages,
        patch("workload.KafkaWorkload.read", return_value=["gandalf=grey"]),
        patch("workload.KafkaWorkload.disable_enable") as patched_disable_enable,
        patch("workload.KafkaWorkload.start") as patched_start,
        patch("ops.framework.EventBase.defer") as patched_defer,
    ):
        ctx.run(ctx.on.storage_attached(storage), state_in)

    # Then
    assert patched_format_storages.call_count == 1
    assert patched_disable_enable.call_count == 1
    assert patched_start.call_count == 1
    assert patched_defer.call_count == 0


def test_config_changed_updates_server_properties(ctx: Context, base_state: State) -> None:
    """Checks that new charm/unit config writes server config to unit on config changed hook."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    restart_peer = PeerRelation("restart", "rolling_op")
    state_in = dataclasses.replace(
        base_state,
        relations=[cluster_peer, restart_peer],
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


def test_config_changed_requests_new_certificate(
    ctx: Context, base_state: State, zk_data: dict[str, str]
) -> None:
    """Checks that if there is a diff in SANs, that a new certificate is requested."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    restart_peer = PeerRelation("restart", "rolling_op")
    state_in = dataclasses.replace(
        base_state,
        relations=[cluster_peer, restart_peer],
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
        patch("managers.config.ConfigManager.set_client_properties"),
        patch("events.tls.TLSHandler._request_certificate_renewal") as request_certificate_renewal,
        patch(
            "managers.tls.TLSManager.get_current_sans",
            return_value={"sans_ip": ["earendil"], "sans_dns": ["denethor"]},
        ),
        patch(
            "managers.tls.TLSManager.build_sans",
            return_value={"sans_ip": ["earendil"], "sans_dns": ["aragorn"]},
        ),
        patch(
            "charms.rolling_ops.v0.rollingops.RollingOpsManager._on_run_with_lock", autospec=True
        ),
    ):
        ctx.run(ctx.on.config_changed(), state_in)

    # Then
    assert request_certificate_renewal.call_count


def test_config_changed_does_not_request_new_certificate_for_slashes(
    ctx: Context, base_state: State, zk_data: dict[str, str]
) -> None:
    """Checks that if there is a diff in SANs, that a new certificate is not requested if the SAN was the unit|app name."""
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    restart_peer = PeerRelation("restart", "rolling_op")
    state_in = dataclasses.replace(
        base_state,
        relations=[cluster_peer, restart_peer],
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
        patch("managers.config.ConfigManager.set_client_properties"),
        patch("events.tls.TLSHandler._request_certificate_renewal") as request_certificate_renewal,
        patch(
            "managers.tls.TLSManager.get_current_sans",
            return_value={"sans_ip": ["earendil"], "sans_dns": [CHARM_KEY]},
        ),
        patch(
            "managers.tls.TLSManager.build_sans",
            return_value={"sans_ip": ["earendil"], "sans_dns": [f"{CHARM_KEY}/0"]},
        ),
        patch(
            "charms.rolling_ops.v0.rollingops.RollingOpsManager._on_run_with_lock", autospec=True
        ),
    ):
        ctx.run(ctx.on.config_changed(), state_in)

    # Then
    assert not request_certificate_renewal.call_count


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
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, restart_peer])

    with (
        patch(
            "managers.config.ConfigManager.server_properties",
            new_callable=PropertyMock,
            return_value=["gandalf=grey"],
        ),
        patch("events.broker.BrokerOperator.healthy", return_value=True),
        patch("workload.KafkaWorkload.read", return_value=["gandalf=white"]),
        patch("events.upgrade.KafkaUpgrade.idle", return_value=True),
        patch("managers.auth.AuthManager.add_user"),
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


def test_workload_version_is_set(ctx: Context, base_state: State):
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
