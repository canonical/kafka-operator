#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from ops import StartEvent
from scenario import Context, PeerRelation, Relation, State

from charm import KafkaCharm
from literals import (
    BALANCER,
    INTERNAL_USERS,
    PEER,
    ZK,
    Status,
)

pytestmark = pytest.mark.balancer

logger = logging.getLogger(__name__)


CONFIG = yaml.safe_load(Path("./config.yaml").read_text())
ACTIONS = yaml.safe_load(Path("./actions.yaml").read_text())
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())


@pytest.fixture()
def charm_configuration():
    """Enable direct mutation on configuration dict."""
    return json.loads(json.dumps(CONFIG))


## BALANCER SIDE


def test_install_blocks_snap_install_failure(charm_configuration):
    # Given
    charm_configuration["options"]["roles"]["default"] = "balancer"
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    state_in = State()

    # When
    with patch("workload.Workload.install", return_value=False), patch("workload.Workload.write"):
        state_out = ctx.run("install", state_in)

    # Then
    assert state_out.unit_status == Status.SNAP_NOT_INSTALLED.value.status


@patch("workload.Workload.stop")
def test_stop_workload_if_not_leader(patched_stopped, charm_configuration):
    # Given
    charm_configuration["options"]["roles"]["default"] = "balancer"
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    state_in = State(leader=False, relations=[])

    # When
    ctx.run("start", state_in)

    # Then
    assert patched_stopped.called_once


def test_ready_to_start_maintenance_no_peer_relation(charm_configuration):
    # Given
    charm_configuration["options"]["roles"]["default"] = "balancer"
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    state_in = State(leader=True, relations=[])

    # When
    ctx.run("start", state_in)

    # Then
    assert len(ctx.emitted_events) == 1
    assert isinstance(ctx.emitted_events[0], StartEvent)
    # assert state_out.unit_status == Status.NO_PEER_RELATION.value.status


def test_ready_to_start_no_balancer(charm_configuration):
    # Given
    charm_configuration["options"]["roles"]["default"] = "balancer"
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    cluster_peer = PeerRelation(PEER, PEER)
    state_in = State(leader=True, relations=[cluster_peer])

    # When
    ctx.run("start", state_in)

    # Then
    assert len(ctx.emitted_events) == 1
    assert isinstance(ctx.emitted_events[0], StartEvent)


def test_ready_to_start_no_zk(charm_configuration):
    # Given
    charm_configuration["options"]["roles"]["default"] = "balancer"
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    cluster_peer = PeerRelation(PEER, PEER)
    balancer_peer = PeerRelation(BALANCER.value, BALANCER.value)
    state_in = State(leader=True, relations=[cluster_peer, balancer_peer])

    # When
    ctx.run("start", state_in)

    # Then
    assert len(ctx.emitted_events) == 1
    assert isinstance(ctx.emitted_events[0], StartEvent)


def test_ready_to_start_no_zk_data(charm_configuration):
    # Given
    charm_configuration["options"]["roles"]["default"] = "balancer"
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    cluster_peer = PeerRelation(PEER, PEER)
    balancer_peer = PeerRelation(BALANCER.value, BALANCER.value)
    relation = Relation(
        interface=ZK,
        endpoint=ZK,
        remote_app_name=ZK,
    )
    state_in = State(leader=True, relations=[cluster_peer, balancer_peer, relation])

    # When
    ctx.run("start", state_in)

    # Then
    assert len(ctx.emitted_events) == 1
    assert isinstance(ctx.emitted_events[0], StartEvent)


def test_ready_to_start_no_balancer_data(charm_configuration, zk_data):
    # Given
    charm_configuration["options"]["roles"]["default"] = "balancer"
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    cluster_peer = PeerRelation(PEER, PEER)
    balancer_peer = PeerRelation(BALANCER.value, BALANCER.value)
    relation = Relation(interface=ZK, endpoint=ZK, remote_app_name=ZK, remote_app_data=zk_data)
    state_in = State(leader=True, relations=[cluster_peer, balancer_peer, relation])

    # When
    ctx.run("start", state_in)

    # Then
    assert len(ctx.emitted_events) == 1
    assert isinstance(ctx.emitted_events[0], StartEvent)


def test_ready_to_start_no_balancer_creds(charm_configuration, zk_data):
    # Given
    charm_configuration["options"]["roles"]["default"] = "balancer"
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    cluster_peer = PeerRelation(PEER, PEER)
    balancer_peer = PeerRelation(
        BALANCER.value,
        BALANCER.value,
        local_app_data={
            "broker-capacities": json.dumps(
                [
                    {
                        "brokerId": "1",
                        "capacity": {
                            "DISK": [{"/path/dat": "50000"}],
                            "CPU": {"num.cores": "8"},
                            "NW_IN": "100000",
                            "NW_OUT": "100000",
                        },
                        "doc": "",
                    }
                ]
            )
        },
    )
    relation = Relation(interface=ZK, endpoint=ZK, remote_app_name=ZK, remote_app_data=zk_data)
    state_in = State(leader=True, relations=[cluster_peer, balancer_peer, relation])

    # When
    ctx.run("start", state_in)

    # Then
    assert len(ctx.emitted_events) == 1
    assert isinstance(ctx.emitted_events[0], StartEvent)


def test_ready_to_start_not_enough_brokers(charm_configuration, zk_data):
    # Given
    charm_configuration["options"]["roles"]["default"] = "balancer"
    ctx = Context(
        KafkaCharm,
        meta=METADATA,
        config=charm_configuration,
        actions=ACTIONS,
    )
    cluster_peer = PeerRelation(
        PEER, PEER, local_app_data={f"{user}-password": "pwd" for user in INTERNAL_USERS}
    )
    balancer_peer = PeerRelation(
        BALANCER.value,
        BALANCER.value,
        local_app_data={
            "broker-capacities": json.dumps(
                [
                    {
                        "brokerId": "1",
                        "capacity": {
                            "DISK": [{"/path/dat": "50000"}],
                            "CPU": {"num.cores": "8"},
                            "NW_IN": "100000",
                            "NW_OUT": "100000",
                        },
                        "doc": "",
                    }
                ]
            )
        },
    )
    relation = Relation(interface=ZK, endpoint=ZK, remote_app_name=ZK, remote_app_data=zk_data)
    state_in = State(leader=True, relations=[cluster_peer, balancer_peer, relation])

    # When
    with (
        patch("workload.BalancerWorkload.write"),
        patch("workload.BalancerWorkload.read"),
        patch("workload.BalancerWorkload.exec"),
        patch("workload.BalancerWorkload.start"),
    ):
        ctx.run("start", state_in)

    # Then
    assert len(ctx.emitted_events) == 1
    assert isinstance(ctx.emitted_events[0], StartEvent)


# def test_rack_awareness_passed_to_balancer(charm_configuration):
#     cores = 8
#     disk = 10240
#     ctx = Context(
#         KafkaCharm,
#         meta=METADATA,
#         config=charm_configuration,
#         actions=ACTIONS,
#     )
#     cluster_peer = PeerRelation(
#         PEER,
#         PEER,
#         local_unit_data={
#             "cores": str(cores),
#             "storages": json.dumps({f'{BROKER.paths["DATA"]}/{STORAGE}/1': disk}),
#         },
#     )
#     balancer_peer = PeerRelation(BALANCER.value, BALANCER.value)

#     state_in = State(leader=True, relations=[cluster_peer, balancer_peer])
#     # When

#     with (
#         patch(
#             "managers.config.ConfigManager.rack_properties",
#             new_callable=PropertyMock,
#             return_value=["broker.rack=gondor-west"],
#         ),
#         patch(
#             "events.broker.BrokerOperator.healthy", new_callable=PropertyMock, return_value=True
#         ),
#     ):
#         state_out = ctx.run(balancer_peer.changed_event, state_in)

#     # Then
#     assert state_out.relations[1].local_app_data["rack_aware"] == "true"


# def test_secrets_requested_by_balancer_on_relation_creation(charm_configuration):
#     # Given
#     charm_configuration["options"]["role"]["default"] = "balancer"
#     ctx = Context(
#         KafkaCharm,
#         meta=METADATA,
#         config=charm_configuration,
#         actions=ACTIONS,
#     )
#     peer = PeerRelation(PEER, PEER)
#     relation = Relation(
#         interface=BALANCER.value,
#         endpoint=BALANCER_SERVICE,
#         remote_app_name=BROKER.value,
#     )
#     state_in = State(leader=True, relations=[peer, relation])

#     # When
#     state_out = ctx.run(relation.created_event, state_in)

#     # Then
#     assert (
#         json.loads(state_out.relations[1].local_app_data["requested-secrets"])
#         == BALANCER.requested_secrets
#     )


# def test_broker_relation_broken_stops_service(charm_configuration):
#     # Given
#     charm_configuration["options"]["role"]["default"] = "balancer"
#     ctx = Context(
#         KafkaCharm,
#         meta=METADATA,
#         config=charm_configuration,
#         actions=ACTIONS,
#     )
#     peer = PeerRelation(PEER, PEER)
#     relation = Relation(
#         interface=BALANCER.value,
#         endpoint=BALANCER_SERVICE,
#         remote_app_name=BROKER.value,
#         local_app_data={
#             "requested-secrets": json.dumps(BALANCER.requested_secrets),
#             "topic": BALANCER_TOPIC,
#             "extra-user-roles": ADMIN_USER,
#         },
#         remote_app_data={},
#     )
#     state_in = State(leader=True, relations=[peer, relation])

#     # When
#     with patch("workload.BalancerWorkload.stop") as patched_stop_snap_service:
#         state_out = ctx.run(relation.broken_event, state_in)

#     patched_stop_snap_service.assert_called_once()
#     assert state_out.unit_status == Status.BROKER_NOT_RELATED.value.status


# def test_extract_fields_from_secrets(charm_configuration):

#     # Given
#     charm_configuration["options"]["role"]["default"] = "balancer"
#     ctx = Context(
#         KafkaCharm,
#         meta=METADATA,
#         config=charm_configuration,
#         actions=ACTIONS,
#     )
#     peer = PeerRelation(PEER, PEER)
#     secret_kafka = Secret(
#         "secret-kafka",
#         contents={0: {"username": "foo", "password": "bar"}},
#         label="balancer-service.9.kafka.secret",  # we should predict this field
#     )
#     relation = Relation(
#         interface=BALANCER.value,
#         endpoint=BALANCER_SERVICE,
#         remote_app_name=BROKER.value,
#         local_app_data={
#             "requested-secrets": json.dumps(BALANCER.requested_secrets),
#             "topic": BALANCER_TOPIC,
#             "extra-user-roles": ADMIN_USER,
#         },
#         remote_app_data={"secret-kafka": secret_kafka.id},
#     )
#     state_in = State(leader=True, relations=[peer, relation], secrets=[secret_kafka])

#     # When

#     with (
#         patch("workload.BalancerWorkload.write"),
#         ctx.manager(relation.changed_event, state_in) as manager,
#     ):
#         charm: KafkaCharm = manager.charm
#         assert charm.state.balancer.password == "bar"


# ## BROKER SIDE


# def test_balancer_relation_created_defers_if_not_ready(charm_configuration):
#     """Checks event is deferred if not ready on balancer relation created hook."""
#     ctx = Context(
#         KafkaCharm,
#         meta=METADATA,
#         config=charm_configuration,
#         actions=ACTIONS,
#     )
#     peer = PeerRelation(PEER, PEER)
#     relation = Relation(
#         interface=BROKER.value,
#         endpoint=BALANCER_RELATION,
#         remote_app_name=BALANCER.value,
#         remote_app_data={
#             "requested-secrets": json.dumps(BALANCER.requested_secrets),
#             "topic": BALANCER_TOPIC,
#             "extra-user-roles": ADMIN_USER,
#         },
#     )
#     state_in = State(leader=True, relations=[peer, relation])

#     # When
#     with (
#         patch("charm.KafkaCharm.healthy", new_callable=PropertyMock, return_value=False),
#         patch("managers.auth.AuthManager.add_user") as patched_add_user,
#         patch("ops.framework.EventBase.defer") as patched_defer,
#     ):
#         _ = ctx.run(relation.changed_event, state_in)

#     # Then
#     patched_add_user.assert_not_called()
#     patched_defer.assert_called()


# def test_capabilities_passed_to_balancer(charm_configuration):
#     cores = "8"
#     disk = "10240"
#     ctx = Context(
#         KafkaCharm,
#         meta=METADATA,
#         config=charm_configuration,
#         actions=ACTIONS,
#     )
#     peer = PeerRelation(
#         PEER,
#         PEER,
#         local_unit_data={
#             "cores": (cores),
#             "storages": json.dumps({f'{BROKER.paths["DATA"]}/{STORAGE}/1': disk}),
#         },
#         peers_data={
#             2: {
#                 "cores": (cores),
#                 "storages": json.dumps({f'{BROKER.paths["DATA"]}/{STORAGE}/2': disk}),
#             }
#         },
#     )
#     relation = Relation(
#         interface=BROKER.value,
#         endpoint=BALANCER_RELATION,
#         remote_app_name=BALANCER.value,
#         remote_app_data={
#             "requested-secrets": json.dumps(BALANCER.requested_secrets),
#             "topic": BALANCER_TOPIC,
#             "extra-user-roles": ADMIN_USER,
#         },
#     )

#     state_in = State(leader=True, relations=[peer, relation])
#     # When
#     with patch("charm.KafkaCharm.healthy", new_callable=PropertyMock, return_value=True):
#         state_out = ctx.run(relation.changed_event, state_in)

#     # Then
#     assert state_out.relations[1].local_app_data["broker-capacities"]
#     broker_capacities = json.loads(state_out.relations[1].local_app_data["broker-capacities"])
#     assert len(broker_capacities["brokerCapacities"]) == 2
#     assert broker_capacities["brokerCapacities"][0]["capacity"]["CPU"]["num.cores"] == cores
#     assert (
#         broker_capacities["brokerCapacities"][0]["capacity"]["DISK"][
#             f'{BROKER.paths["DATA"]}/{STORAGE}/1'
#         ]
#         == disk
#     )


# def test_rack_awareness_passed_to_balancer(charm_configuration):
#     cores = 8
#     disk = 10240
#     ctx = Context(
#         KafkaCharm,
#         meta=METADATA,
#         config=charm_configuration,
#         actions=ACTIONS,
#     )
#     peer = PeerRelation(
#         PEER,
#         PEER,
#         local_unit_data={
#             "cores": str(cores),
#             "storages": json.dumps({f'{BROKER.paths["DATA"]}/{STORAGE}/1': disk}),
#         },
#     )
#     relation = Relation(
#         interface=BROKER.value,
#         endpoint=BALANCER_RELATION,
#         remote_app_name=BALANCER.value,
#         remote_app_data={
#             "requested-secrets": json.dumps(BALANCER.requested_secrets),
#             "topic": BALANCER_TOPIC,
#             "extra-user-roles": ADMIN_USER,
#         },
#     )

#     state_in = State(leader=True, relations=[peer, relation])
#     # When

#     with (
#         patch(
#             "managers.config.ConfigManager.rack_properties",
#             new_callable=PropertyMock,
#             return_value=["broker.rack=gondor-west"],
#         ),
#         patch("charm.KafkaCharm.healthy", new_callable=PropertyMock, return_value=True),
#     ):
#         state_out = ctx.run(relation.changed_event, state_in)

#     # Then
#     assert state_out.relations[1].local_app_data["rack_aware"] == "true"
