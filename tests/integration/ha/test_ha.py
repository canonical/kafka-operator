#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import logging
from collections.abc import AsyncGenerator

import pytest
from pytest_operator.plugin import OpsTest

from integration.ha.continuous_writes import ContinuousWrites
from integration.ha.ha_helpers import (
    add_k8s_hosts,
    assert_continuous_writes_consistency,
    delete_pod,
    deploy_chaos_mesh,
    destroy_chaos_mesh,
    get_topic_description,
    get_topic_offsets,
    isolate_instance_from_cluster,
    modify_pebble_restart_delay,
    remove_instance_isolation,
    remove_k8s_hosts,
    send_control_signal,
)
from integration.helpers import (
    APP_NAME,
    DUMMY_NAME,
    KAFKA_CONTAINER,
    REL_NAME_ADMIN,
    ZK_NAME,
    check_logs,
)

RESTART_DELAY = 60
CLIENT_TIMEOUT = 30
REELECTION_TIME = 25

logger = logging.getLogger(__name__)


@pytest.fixture()
async def c_writes(ops_test: OpsTest):
    """Creates instance of the ContinuousWrites."""
    app = APP_NAME
    return ContinuousWrites(ops_test, app)


@pytest.fixture()
async def c_writes_runner(ops_test: OpsTest, c_writes: ContinuousWrites):
    """Starts continuous write operations and clears writes at the end of the test."""
    add_k8s_hosts(ops_test=ops_test)
    c_writes.start()
    yield
    c_writes.clear()
    remove_k8s_hosts(ops_test=ops_test)
    logger.info("\n\n\n\nThe writes have been cleared.\n\n\n\n")


@pytest.fixture()
async def restart_delay(ops_test: OpsTest):
    modify_pebble_restart_delay(ops_test=ops_test, policy="extend")
    yield
    modify_pebble_restart_delay(ops_test=ops_test, policy="restore")


@pytest.fixture()
async def chaos_mesh(ops_test: OpsTest) -> AsyncGenerator:
    """Deploys chaos mesh to the namespace and uninstalls it at the end."""
    deploy_chaos_mesh(ops_test.model.info.name)

    yield

    remove_instance_isolation(ops_test)
    destroy_chaos_mesh(ops_test.model.info.name)


@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, kafka_charm, app_charm):
    await asyncio.gather(
        ops_test.model.deploy(
            kafka_charm,
            application_name=APP_NAME,
            num_units=1,
            resources={"kafka-image": KAFKA_CONTAINER},
            trust=True,
            config={"expose_external": "nodeport"},
        ),
        ops_test.model.deploy(ZK_NAME, channel="3/edge", num_units=1, trust=True),
        ops_test.model.deploy(app_charm, application_name=DUMMY_NAME, trust=True),
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME], timeout=2000)

    await ops_test.model.add_relation(APP_NAME, ZK_NAME)
    async with ops_test.fast_forward(fast_interval="20s"):
        await asyncio.sleep(90)

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME],
        idle_period=30,
        status="active",
        timeout=2000,
        raise_on_error=False,
    )

    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")

    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, DUMMY_NAME, ZK_NAME], idle_period=30, status="active", timeout=2000
        )


# run this test early, in case of resource limits on runners with too many units
async def test_multi_cluster_isolation(ops_test: OpsTest, kafka_charm):
    second_kafka_name = f"{APP_NAME}-two"
    second_zk_name = f"{ZK_NAME}-two"

    await asyncio.gather(
        ops_test.model.deploy(
            kafka_charm,
            application_name=second_kafka_name,
            num_units=1,
            resources={"kafka-image": KAFKA_CONTAINER},
            trust=True,
            config={"expose_external": "nodeport"},
        ),
        ops_test.model.deploy(
            ZK_NAME, application_name=second_zk_name, channel="3/edge", trust=True
        ),
    )
    await ops_test.model.add_relation(second_kafka_name, second_zk_name)

    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(
            apps=[second_kafka_name, second_zk_name],
            idle_period=30,
            status="active",
            timeout=2000,
            raise_on_error=False,
        )

    assert ops_test.model.applications[second_kafka_name].status == "active"
    assert ops_test.model.applications[second_zk_name].status == "active"

    # produce to first cluster
    action = await ops_test.model.units.get(f"{DUMMY_NAME}/0").run_action("produce")
    await action.wait()
    await asyncio.sleep(10)
    await ops_test.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME], timeout=1000, idle_period=30)
    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[DUMMY_NAME].status == "active"

    # logs exist on first cluster
    check_logs(
        ops_test=ops_test,
        kafka_unit_name=f"{APP_NAME}/0",
        topic="test-topic",
    )

    # Check that logs are not found on the second cluster
    with pytest.raises(AssertionError):
        check_logs(
            ops_test=ops_test,
            kafka_unit_name=f"{second_kafka_name}/0",
            topic="test-topic",
        )

    # fast removal of second cluster
    remove_apps = f"remove-application --force --destroy-storage --no-wait --no-prompt {second_kafka_name} {second_zk_name}"
    await ops_test.juju(*remove_apps.split(), check=True)


async def test_scale_up_zk_kafka(ops_test: OpsTest):
    await ops_test.model.applications[APP_NAME].add_units(count=2)
    await ops_test.model.applications[ZK_NAME].add_units(count=2)
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[APP_NAME].units) == 3)
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[ZK_NAME].units) == 3)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME], status="active", timeout=1000, idle_period=30
    )


async def test_kill_broker_with_topic_leader(
    ops_test: OpsTest,
    restart_delay,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    # Let some time pass to create messages
    await asyncio.sleep(5)
    topic_description = get_topic_description(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    initial_leader_num = topic_description.leader

    logger.info(
        f"Killing broker of leader for topic '{ContinuousWrites.TOPIC_NAME}': {initial_leader_num}"
    )
    await send_control_signal(
        ops_test=ops_test, unit_name=f"{APP_NAME}/{initial_leader_num}", signal="SIGKILL"
    )

    # Give time for the remaining units to notice leader going down
    await asyncio.sleep(REELECTION_TIME)

    # Check offsets after killing leader
    initial_offsets = get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)

    # verify replica is not in sync and check that leader changed
    topic_description = get_topic_description(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    assert initial_leader_num != topic_description.leader
    assert topic_description.in_sync_replicas == {0, 1, 2} - {initial_leader_num}

    # Give time for the service to restart
    await asyncio.sleep(RESTART_DELAY * 2)

    topic_description = get_topic_description(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    next_offsets = get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)

    assert topic_description.in_sync_replicas == {0, 1, 2}
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)


async def test_restart_broker_with_topic_leader(
    ops_test: OpsTest,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    topic_description = get_topic_description(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    leader_num = topic_description.leader

    logger.info(
        f"Restarting broker of leader for topic '{ContinuousWrites.TOPIC_NAME}': {leader_num}"
    )
    await send_control_signal(
        ops_test=ops_test, unit_name=f"{APP_NAME}/{leader_num}", signal="SIGTERM"
    )
    # Give time for the service to restart
    await asyncio.sleep(REELECTION_TIME * 2)

    initial_offsets = get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    await asyncio.sleep(CLIENT_TIMEOUT)
    next_offsets = get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)

    topic_description = get_topic_description(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    assert topic_description.in_sync_replicas == {0, 1, 2}
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)


async def test_freeze_broker_with_topic_leader(
    ops_test: OpsTest,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    topic_description = get_topic_description(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    initial_leader_num = topic_description.leader

    logger.info(
        f"Freezing broker of leader for topic '{ContinuousWrites.TOPIC_NAME}': {initial_leader_num}"
    )
    await send_control_signal(
        ops_test=ops_test, unit_name=f"{APP_NAME}/{initial_leader_num}", signal="SIGSTOP"
    )
    await asyncio.sleep(REELECTION_TIME * 2)

    # verify replica is not in sync
    topic_description = get_topic_description(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    assert topic_description.in_sync_replicas == {0, 1, 2} - {initial_leader_num}
    assert initial_leader_num != topic_description.leader

    # verify new writes are continuing. Also, check that leader changed
    topic_description = get_topic_description(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    initial_offsets = get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    await asyncio.sleep(CLIENT_TIMEOUT * 2)
    next_offsets = get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)

    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    # Un-freeze the process
    logger.info(f"Un-freezing broker: {initial_leader_num}")
    await send_control_signal(
        ops_test=ops_test, unit_name=f"{APP_NAME}/{initial_leader_num}", signal="SIGCONT"
    )
    await asyncio.sleep(REELECTION_TIME)
    topic_description = get_topic_description(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)

    # verify the unit is now rejoined the cluster
    assert topic_description.in_sync_replicas == {0, 1, 2}

    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)


async def test_full_cluster_crash(
    ops_test: OpsTest,
    restart_delay,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    # Let some time pass for messages to be produced
    await asyncio.sleep(10)

    logger.info("Killing all brokers...")
    # kill all units "simultaneously"
    await asyncio.gather(
        *[
            send_control_signal(ops_test, unit.name, signal="SIGKILL")
            for unit in ops_test.model.applications[APP_NAME].units
        ]
    )
    # Give time for the service to restart
    await asyncio.sleep(RESTART_DELAY * 2)

    topic_description = get_topic_description(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    initial_offsets = get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    await asyncio.sleep(CLIENT_TIMEOUT * 2)
    next_offsets = get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)

    assert int(next_offsets[-1]) > int(initial_offsets[-1])
    assert topic_description.in_sync_replicas == {0, 1, 2}

    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)


async def test_full_cluster_restart(
    ops_test: OpsTest,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    # Let some time pass for messages to be produced
    await asyncio.sleep(10)

    logger.info("Restarting all brokers...")
    # Restart all units "simultaneously"
    await asyncio.gather(
        *[
            send_control_signal(ops_test, unit.name, signal="SIGTERM")
            for unit in ops_test.model.applications[APP_NAME].units
        ]
    )
    # Give time for the service to restart
    await asyncio.sleep(REELECTION_TIME * 2)

    initial_offsets = get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    await asyncio.sleep(CLIENT_TIMEOUT * 2)
    next_offsets = get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    topic_description = get_topic_description(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)

    assert int(next_offsets[-1]) > int(initial_offsets[-1])
    assert topic_description.in_sync_replicas == {0, 1, 2}

    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)


async def test_pod_reschedule(
    ops_test: OpsTest,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    # Let some time pass to create messages
    await asyncio.sleep(5)
    topic_description = get_topic_description(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    initial_leader_num = topic_description.leader

    logger.info(
        f"Killing pod of leader for topic '{ContinuousWrites.TOPIC_NAME}': {initial_leader_num}"
    )
    delete_pod(ops_test, unit_name=f"{APP_NAME}/{initial_leader_num}")

    # let pod reschedule process be noticed up by juju
    async with ops_test.fast_forward("60s"):
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME], idle_period=30, status="active", timeout=1000
        )

    # refresh hosts with the new ip
    remove_k8s_hosts(ops_test=ops_test)
    add_k8s_hosts(ops_test=ops_test)

    # Check offsets after killing leader
    initial_offsets = get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    await asyncio.sleep(CLIENT_TIMEOUT * 2)
    next_offsets = get_topic_offsets(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    topic_description = get_topic_description(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    assert initial_leader_num != topic_description.leader
    assert topic_description.in_sync_replicas == {0, 1, 2}

    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)


@pytest.mark.unstable
async def test_network_cut_without_ip_change(
    ops_test: OpsTest,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
    chaos_mesh,
):
    # Let some time pass for messages to be produced
    await asyncio.sleep(5)

    topic_description = get_topic_description(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    initial_leader_num = topic_description.leader

    logger.info(
        f"Cutting network for leader of topic '{ContinuousWrites.TOPIC_NAME}': {initial_leader_num}"
    )
    isolate_instance_from_cluster(ops_test=ops_test, unit_name=f"{APP_NAME}/{initial_leader_num}")
    await asyncio.sleep(REELECTION_TIME * 2)

    available_unit = f"{APP_NAME}/{next(iter({0, 1, 2} - {initial_leader_num}))}"
    # verify replica is not in sync
    topic_description = get_topic_description(
        ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME, unit_name=available_unit
    )
    assert topic_description.in_sync_replicas == {0, 1, 2} - {initial_leader_num}
    assert initial_leader_num != topic_description.leader

    # verify new writes are continuing. Also, check that leader changed
    topic_description = get_topic_description(
        ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME, unit_name=available_unit
    )
    initial_offsets = get_topic_offsets(
        ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME, unit_name=available_unit
    )
    await asyncio.sleep(CLIENT_TIMEOUT * 2)
    next_offsets = get_topic_offsets(
        ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME, unit_name=available_unit
    )

    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    # Release the network
    logger.info(f"Releasing network of broker: {initial_leader_num}")
    remove_instance_isolation(ops_test)

    await asyncio.sleep(REELECTION_TIME * 2)

    async with ops_test.fast_forward(fast_interval="15s"):
        result = c_writes.stop()
        await asyncio.sleep(CLIENT_TIMEOUT * 8)

    # verify the unit is now rejoined the cluster
    topic_description = get_topic_description(ops_test=ops_test, topic=ContinuousWrites.TOPIC_NAME)
    assert topic_description.in_sync_replicas == {0, 1, 2}

    assert_continuous_writes_consistency(result=result)
