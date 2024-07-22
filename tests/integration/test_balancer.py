#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
from subprocess import CalledProcessError

import pytest
from pytest_operator.plugin import OpsTest

from literals import PEER_CLUSTER_ORCHESTRATOR_RELATION, PEER_CLUSTER_RELATION

from .helpers import (
    APP_NAME,
    ZK_NAME,
    balancer_is_ready,
    balancer_is_running,
    balancer_is_secure,
    get_replica_count_by_broker_id,
)

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.balancer

BALANCER_APP = "balancer"
PRODUCER_APP = "producer"

@pytest.fixture(params=[APP_NAME, BALANCER_APP], scope="module")
async def balancer_app(ops_test: OpsTest, request):
    yield request.param

class TestBalancer:
    @pytest.mark.abort_on_fail
    async def test_build_and_deploy(
        self, ops_test: OpsTest, kafka_charm, balancer_app
    ):
        await ops_test.model.add_machine(series="jammy")
        machine_ids = await ops_test.model.get_machines()

        await asyncio.gather(
            ops_test.model.deploy(
                kafka_charm,
                application_name=APP_NAME,
                num_units=2,
                series="jammy",
                to=machine_ids[0],
                config={"roles": "broker,balancer" if balancer_app == APP_NAME else "broker"},
            ),
            ops_test.model.deploy(
                ZK_NAME, channel="edge", application_name=ZK_NAME, num_units=1, series="jammy"
            ),
        )

        if balancer_app != APP_NAME:
            await ops_test.model.deploy(
                kafka_charm,
                application_name=balancer_app,
                num_units=1,
                series="jammy",
                config={"roles": balancer_app},
            )

        await ops_test.model.wait_for_idle(
            apps=list({APP_NAME, ZK_NAME, balancer_app}), idle_period=30, timeout=3600
        )
        assert ops_test.model.applications[APP_NAME].status == "blocked"
        assert ops_test.model.applications[ZK_NAME].status == "active"
        assert ops_test.model.applications[balancer_app].status == "blocked"

    @pytest.mark.abort_on_fail
    async def test_relate_not_enough_brokers(self, ops_test: OpsTest, balancer_app):
        await ops_test.model.add_relation(APP_NAME, ZK_NAME)
        if balancer_app != APP_NAME:
            await ops_test.model.add_relation(
                f"{APP_NAME}:{PEER_CLUSTER_RELATION}",
                f"{BALANCER_APP}:{PEER_CLUSTER_ORCHESTRATOR_RELATION}",
            )

        await ops_test.model.wait_for_idle(
            apps=list({APP_NAME, ZK_NAME, balancer_app}), idle_period=30
        )
        assert ops_test.model.applications[APP_NAME].status == "waiting"

        with pytest.raises(CalledProcessError):
            assert balancer_is_running(
                model_full_name=ops_test.model_full_name, app_name=balancer_app
            )

    @pytest.mark.abort_on_fail
    async def test_minimum_brokers_balancer_starts(self, ops_test: OpsTest, balancer_app):
        await ops_test.model.applications[APP_NAME].add_units(count=2)
        await ops_test.model.block_until(
            lambda: len(ops_test.model.applications[APP_NAME].units) == 4
        )
        await ops_test.model.wait_for_idle(
            apps=list({APP_NAME, ZK_NAME, balancer_app}),
            status="active",
            timeout=1800,
            idle_period=30,
        )

        assert balancer_is_running(model_full_name=ops_test.model_full_name, app_name=balancer_app)
        assert balancer_is_secure(ops_test, app_name=balancer_app)

    @pytest.mark.abort_on_fail
    async def test_change_leader(self, ops_test: OpsTest, balancer_app):
        for unit in ops_test.model.applications[APP_NAME].units:
            if await unit.is_leader_from_status():
                leader_unit = unit

        await leader_unit.destroy(force=True, destroy_storage=True, max_wait=0)
        await ops_test.model.block_until(
            lambda: len(ops_test.model.applications[APP_NAME].units) == 3
        )
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME], status="active", timeout=1800, idle_period=60
        )
        assert balancer_is_running(model_full_name=ops_test.model_full_name, app_name=balancer_app)
        assert balancer_is_secure(ops_test, app_name=balancer_app)

    @pytest.mark.abort_on_fail
    async def test_balancer_monitor_state(self, ops_test: OpsTest, balancer_app):
        await ops_test.model.deploy(
            "kafka-test-app",
            application_name=PRODUCER_APP,
            num_units=1,
            series="jammy",
            config={
                "topic_name": "HOT-TOPIC",
                "num_messages": 100000,
                "role": "producer",
                "partitions": 100,
                "replication_factor": "3",
            },
        )

        # creating topics with a replication-factor of 3 so all current Kafka units have some partitions
        await ops_test.model.add_relation(PRODUCER_APP, APP_NAME)
        await ops_test.model.wait_for_idle(
            apps=list({APP_NAME, ZK_NAME, PRODUCER_APP, balancer_app}),
            status="active",
            timeout=1800,
            idle_period=30,
        )

        assert balancer_is_ready(ops_test=ops_test, app_name=balancer_app)

    @pytest.mark.abort_on_fail
    async def test_add_unit_full_rebalance(self, ops_test: OpsTest, balancer_app):
        await ops_test.model.applications[APP_NAME].add_units(
            count=1  # up to 4, new unit won't have any partitions
        )
        await ops_test.model.block_until(
            lambda: len(ops_test.model.applications[APP_NAME].units) == 4
        )
        await ops_test.model.wait_for_idle(
            apps=list({APP_NAME, ZK_NAME, PRODUCER_APP, balancer_app}),
            status="active",
            timeout=1800,
            idle_period=30,
        )
        assert balancer_is_ready(ops_test=ops_test, app_name=balancer_app)

        # verify CC can find the new broker_id 3, with no replica partitions allocated
        new_broker_replica_count = get_replica_count_by_broker_id(ops_test, balancer_app).get(
            "4", ""
        )
        assert (
            not new_broker_replica_count
            or not new_broker_replica_count == "0"
            or not int(new_broker_replica_count)
        )

        for unit in ops_test.model.applications[APP_NAME].units:
            if await unit.is_leader_from_status():
                leader_unit = unit

        rebalance_action_dry_run = await ops_test.model.units.get(leader_unit).run_action(
            "rebalance", params={"mode": "full", "dry-run": "True"}, timeout=600, block=True
        )
        response = await rebalance_action_dry_run.wait()
        print(f"{response.results=}")
        assert response.results

        rebalance_action = await ops_test.model.units.get(leader_unit).run_action(
            "rebalance", params={"mode": "full", "dry-run": "False"}, timeout=600, block=True
        )
        response = await rebalance_action.wait()
        print(f"{response=}")

        assert int(
            get_replica_count_by_broker_id(ops_test, balancer_app).get("4", "0")
        )  # replicas were successfully moved

    @pytest.mark.abort_on_fail
    async def test_remove_unit_full_rebalance(self, ops_test: OpsTest, balancer_app):
        # storing the current replica counts of 0, 1, 2 - they will persist
        pre_rebalance_replica_counts = {
            key: value
            for key, value in get_replica_count_by_broker_id(ops_test, balancer_app).items()
            if key != "4"
        }

        # removing brokerid 3 ungracefully
        await ops_test.model.applications[APP_NAME].destroy_units(f"{APP_NAME}/4")
        await ops_test.model.block_until(
            lambda: len(ops_test.model.applications[APP_NAME].units) == 3
        )
        await ops_test.model.wait_for_idle(
            apps=list({APP_NAME, ZK_NAME, PRODUCER_APP, balancer_app}),
            status="active",
            timeout=1800,
            idle_period=30,
        )
        assert balancer_is_ready(ops_test=ops_test, app_name=balancer_app)

        for unit in ops_test.model.applications[APP_NAME].units:
            if await unit.is_leader_from_status():
                leader_unit = unit

        rebalance_action_dry_run = await ops_test.model.units.get(leader_unit).run_action(
            "rebalance", params={"mode": "full", "dry-run": "True"}, timeout=600, block=True
        )
        response = await rebalance_action_dry_run.wait()
        print(f"{response.results=}")
        assert response.results

        rebalance_action = await ops_test.model.units.get(leader_unit).run_action(
            "rebalance", params={"mode": "full", "dry-run": "False"}, timeout=600, block=True
        )
        response = await rebalance_action.wait()
        print(f"{response=}")

        post_rebalance_replica_counts = get_replica_count_by_broker_id(ops_test, balancer_app)

        assert not int(post_rebalance_replica_counts.get("4", "0"))

        # looping over all brokerids, as rebalance *should* be even across all
        for key, value in pre_rebalance_replica_counts.items():
            # verify that post-rebalance, surviving units increased replica counts
            assert int(value) < int(post_rebalance_replica_counts.get(key, "0"))
