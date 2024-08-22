#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import os
from subprocess import CalledProcessError

import pytest
from pytest_operator.plugin import OpsTest

from literals import (
    PEER_CLUSTER_ORCHESTRATOR_RELATION,
    PEER_CLUSTER_RELATION,
    SUBSTRATE,
    TLS_RELATION,
)

from .helpers import (
    APP_NAME,
    ZK_NAME,
    balancer_exporter_is_up,
    balancer_is_ready,
    balancer_is_running,
    balancer_is_secure,
    get_replica_count_by_broker_id,
)

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.balancer

BALANCER_APP = "balancer"
PRODUCER_APP = "producer"
TLS_NAME = "self-signed-certificates"


class TestBalancer:

    deployment_strat: str = os.environ.get("DEPLOYMENT", "multi")
    balancer_app: str = {"single": APP_NAME, "multi": "balancer"}[deployment_strat]

    @pytest.mark.abort_on_fail
    async def test_build_and_deploy(self, ops_test: OpsTest, kafka_charm):
        await ops_test.model.add_machine(series="jammy")
        machine_ids = await ops_test.model.get_machines()

        await asyncio.gather(
            ops_test.model.deploy(
                kafka_charm,
                application_name=APP_NAME,
                num_units=1,
                series="jammy",
                to=machine_ids[0],
                config={
                    "roles": "broker,balancer" if self.balancer_app == APP_NAME else "broker",
                    "profile": "testing",
                },
                trust=True,
            ),
            ops_test.model.deploy(
                ZK_NAME,
                channel="3/edge",
                application_name=ZK_NAME,
                num_units=1,
                series="jammy",
                trust=True,
            ),
            ops_test.model.deploy(
                "kafka-test-app",
                application_name=PRODUCER_APP,
                channel="edge",
                num_units=1,
                series="jammy",
                config={
                    "topic_name": "HOT-TOPIC",
                    "num_messages": 100000,
                    "role": "producer",
                    "partitions": 20,
                    "replication_factor": "3",
                },
                trust=True,
            ),
        )

        if self.balancer_app != APP_NAME:
            await ops_test.model.deploy(
                kafka_charm,
                application_name=self.balancer_app,
                num_units=1,
                series="jammy",
                config={
                    "roles": self.balancer_app,
                    "profile": "testing",
                },
                trust=True,
            )

        await ops_test.model.wait_for_idle(
            apps=list({APP_NAME, ZK_NAME, self.balancer_app}),
            idle_period=30,
            timeout=1800,
            raise_on_error=False,
        )
        assert ops_test.model.applications[APP_NAME].status == "blocked"
        assert ops_test.model.applications[ZK_NAME].status == "active"
        assert ops_test.model.applications[self.balancer_app].status == "blocked"

    @pytest.mark.abort_on_fail
    async def test_relate_not_enough_brokers(self, ops_test: OpsTest):
        await ops_test.model.add_relation(APP_NAME, ZK_NAME)
        await ops_test.model.add_relation(PRODUCER_APP, APP_NAME)
        if self.balancer_app != APP_NAME:
            await ops_test.model.add_relation(
                f"{APP_NAME}:{PEER_CLUSTER_RELATION}",
                f"{BALANCER_APP}:{PEER_CLUSTER_ORCHESTRATOR_RELATION}",
            )

        await ops_test.model.wait_for_idle(
            apps=list({APP_NAME, ZK_NAME, self.balancer_app}), idle_period=30
        )

        async with ops_test.fast_forward(fast_interval="20s"):
            await asyncio.sleep(120)  # ensure update-status adds broker-capacities if missed

        assert ops_test.model.applications[self.balancer_app].status == "waiting"

        with pytest.raises(CalledProcessError):
            assert balancer_is_running(
                model_full_name=ops_test.model_full_name, app_name=self.balancer_app
            )

    @pytest.mark.abort_on_fail
    async def test_minimum_brokers_balancer_starts(self, ops_test: OpsTest):
        await ops_test.model.applications[APP_NAME].add_units(count=2)
        await ops_test.model.block_until(
            lambda: len(ops_test.model.applications[APP_NAME].units) == 3
        )
        await ops_test.model.wait_for_idle(
            apps=list({APP_NAME, ZK_NAME, self.balancer_app, PRODUCER_APP}),
            status="active",
            timeout=1800,
            idle_period=60,
        )

        assert balancer_is_running(
            model_full_name=ops_test.model_full_name, app_name=self.balancer_app
        )
        assert balancer_is_secure(ops_test, app_name=self.balancer_app)

    @pytest.mark.abort_on_fail
    async def test_balancer_exporter_endpoints(self, ops_test: OpsTest):
        assert balancer_exporter_is_up(ops_test.model_full_name, self.balancer_app)

    @pytest.mark.abort_on_fail
    async def test_balancer_monitor_state(self, ops_test: OpsTest):
        assert balancer_is_ready(ops_test=ops_test, app_name=self.balancer_app)

    @pytest.mark.abort_on_fail
    @pytest.mark.skipif(
        deployment_strat == "single", reason="Testing full rebalance on large deployment"
    )
    async def test_add_unit_full_rebalance(self, ops_test: OpsTest):
        await ops_test.model.applications[APP_NAME].add_units(
            count=1  # up to 4, new unit won't have any partitions
        )
        await ops_test.model.block_until(
            lambda: len(ops_test.model.applications[APP_NAME].units) == 4
        )
        await ops_test.model.wait_for_idle(
            apps=list({APP_NAME, ZK_NAME, PRODUCER_APP, self.balancer_app}),
            status="active",
            timeout=1800,
            idle_period=30,
        )
        async with ops_test.fast_forward(fast_interval="20s"):
            await asyncio.sleep(120)  # ensure update-status adds broker-capacities if missed

        assert balancer_is_ready(ops_test=ops_test, app_name=self.balancer_app)

        # verify CC can find the new broker_id 3, with no replica partitions allocated
        broker_replica_count = get_replica_count_by_broker_id(ops_test, self.balancer_app)
        new_broker_id = max(map(int, broker_replica_count.keys()))
        new_broker_replica_count = int(broker_replica_count.get(str(new_broker_id), 0))

        assert not new_broker_replica_count

        for unit in ops_test.model.applications[self.balancer_app].units:
            if await unit.is_leader_from_status():
                leader_unit = unit

        rebalance_action = await leader_unit.run_action("rebalance", mode="full", dryrun=False)
        response = await rebalance_action.wait()
        assert response.results

        assert int(
            get_replica_count_by_broker_id(ops_test, self.balancer_app).get(str(new_broker_id), 0)
        )  # replicas were successfully moved

    @pytest.mark.abort_on_fail
    @pytest.mark.skipif(
        deployment_strat == "single", reason="Testing full rebalance on large deployment"
    )
    async def test_remove_unit_full_rebalance(self, ops_test: OpsTest):
        # verify CC can find the new broker_id 3, with no replica partitions allocated
        broker_replica_count = get_replica_count_by_broker_id(ops_test, self.balancer_app)
        new_broker_id = max(map(int, broker_replica_count.keys()))

        # storing the current replica counts of 0, 1, 2 - they will persist
        pre_rebalance_replica_counts = {
            key: value
            for key, value in get_replica_count_by_broker_id(ops_test, self.balancer_app).items()
            if key != str(new_broker_id)
        }

        if SUBSTRATE == "vm":
            # removing broker ungracefully
            await ops_test.model.applications[APP_NAME].destroy_units(
                f"{APP_NAME}/{new_broker_id}"
            )
        else:
            await ops_test.model.applications[APP_NAME].scale(scale_change=-1)

        await ops_test.model.block_until(
            lambda: len(ops_test.model.applications[APP_NAME].units) == 3
        )
        await ops_test.model.wait_for_idle(
            apps=list({APP_NAME, ZK_NAME, PRODUCER_APP, self.balancer_app}),
            status="active",
            timeout=1800,
            idle_period=30,
        )
        async with ops_test.fast_forward(fast_interval="20s"):
            await asyncio.sleep(120)  # ensure update-status adds broker-capacities if missed

        assert balancer_is_ready(ops_test=ops_test, app_name=self.balancer_app)

        for unit in ops_test.model.applications[self.balancer_app].units:
            if await unit.is_leader_from_status():
                leader_unit = unit

        rebalance_action = await leader_unit.run_action("rebalance", mode="full", dryrun=False)
        response = await rebalance_action.wait()
        assert response.results

        post_rebalance_replica_counts = get_replica_count_by_broker_id(ops_test, self.balancer_app)

        assert not int(post_rebalance_replica_counts.get(str(new_broker_id), 0))

        # looping over all brokerids, as rebalance *should* be even across all
        for key, value in pre_rebalance_replica_counts.items():
            # verify that post-rebalance, surviving units increased replica counts
            assert int(value) < int(post_rebalance_replica_counts.get(key, 0))

    @pytest.mark.abort_on_fail
    @pytest.mark.skipif(
        deployment_strat == "multi", reason="Testing full rebalance on single-app deployment"
    )
    async def test_add_unit_targeted_rebalance(self, ops_test: OpsTest):
        assert balancer_is_ready(ops_test=ops_test, app_name=self.balancer_app)
        await ops_test.model.applications[APP_NAME].add_units(
            count=1  # up to 4, new unit won't have any partitions
        )
        await ops_test.model.block_until(
            lambda: len(ops_test.model.applications[APP_NAME].units) == 4
        )
        await ops_test.model.wait_for_idle(
            apps=list({APP_NAME, ZK_NAME, PRODUCER_APP, self.balancer_app}),
            status="active",
            timeout=1800,
            idle_period=30,
        )
        async with ops_test.fast_forward(fast_interval="20s"):
            await asyncio.sleep(120)  # ensure update-status adds broker-capacities if missed

        assert balancer_is_ready(ops_test=ops_test, app_name=self.balancer_app)

        # verify CC can find the new broker_id 3, with no replica partitions allocated
        broker_replica_count = get_replica_count_by_broker_id(ops_test, self.balancer_app)
        new_broker_id = max(map(int, broker_replica_count.keys()))
        pre_rebalance_replica_counts = {
            key: value for key, value in broker_replica_count.items() if key != str(new_broker_id)
        }
        new_broker_replica_count = int(broker_replica_count.get(str(new_broker_id), 0))

        assert not new_broker_replica_count

        for unit in ops_test.model.applications[self.balancer_app].units:
            if await unit.is_leader_from_status():
                leader_unit = unit

        rebalance_action = await leader_unit.run_action(
            "rebalance", mode="add", brokerid=new_broker_id, dryrun=False
        )

        response = await rebalance_action.wait()
        assert response.results

        post_rebalance_replica_counts = get_replica_count_by_broker_id(ops_test, self.balancer_app)

        # Partition only were moved from existing brokers to the new one
        for existing_broker, previous_replica_count in pre_rebalance_replica_counts.items():
            assert previous_replica_count >= post_rebalance_replica_counts.get(
                str(existing_broker)
            )

        # New broker has partition(s)
        assert int(
            get_replica_count_by_broker_id(ops_test, self.balancer_app).get(str(new_broker_id), 0)
        )  # replicas were successfully moved

    @pytest.mark.abort_on_fail
    @pytest.mark.skipif(
        deployment_strat == "multi", reason="Testing full rebalance on single-app deployment"
    )
    async def test_balancer_prepare_unit_removal(self, ops_test: OpsTest):
        assert balancer_is_ready(ops_test=ops_test, app_name=self.balancer_app)
        broker_replica_count = get_replica_count_by_broker_id(ops_test, self.balancer_app)
        new_broker_id = max(map(int, broker_replica_count.keys()))

        # storing the current replica counts of 0, 1, 2 - they will persist
        pre_rebalance_replica_counts = {
            key: value
            for key, value in get_replica_count_by_broker_id(ops_test, self.balancer_app).items()
            if key != str(new_broker_id)
        }

        for unit in ops_test.model.applications[self.balancer_app].units:
            if await unit.is_leader_from_status():
                leader_unit = unit

        assert balancer_is_ready(ops_test=ops_test, app_name=self.balancer_app)

        rebalance_action = await leader_unit.run_action(
            "rebalance",
            mode="remove",
            brokerid=new_broker_id,
            dryrun=False,
        )
        response = await rebalance_action.wait()
        assert response.results

        post_rebalance_replica_counts = get_replica_count_by_broker_id(ops_test, self.balancer_app)

        # Partition only were moved from the removed broker to the other ones
        for existing_broker, previous_replica_count in pre_rebalance_replica_counts.items():
            assert previous_replica_count <= post_rebalance_replica_counts.get(
                str(existing_broker)
            )

        # Replicas were successfully moved
        assert not int(
            get_replica_count_by_broker_id(ops_test, self.balancer_app).get(str(new_broker_id), 0)
        )

    @pytest.mark.abort_on_fail
    async def test_tls(self, ops_test: OpsTest):
        # deploy and integrate tls
        tls_config = {"ca-common-name": "kafka"}

        # FIXME (certs): Unpin the revision once the charm is fixed
        await ops_test.model.deploy(
            TLS_NAME, channel="edge", config=tls_config, series="jammy", revision=163
        )
        await ops_test.model.wait_for_idle(apps=[TLS_NAME], idle_period=15)
        assert ops_test.model.applications[TLS_NAME].status == "active"

        await ops_test.model.add_relation(TLS_NAME, ZK_NAME)
        await ops_test.model.add_relation(TLS_NAME, f"{APP_NAME}:{TLS_RELATION}")

        if self.balancer_app != APP_NAME:
            await ops_test.model.add_relation(TLS_NAME, f"{BALANCER_APP}:{TLS_RELATION}")

        await ops_test.model.wait_for_idle(
            apps=list({APP_NAME, ZK_NAME, self.balancer_app}), idle_period=30, timeout=1800
        )
        async with ops_test.fast_forward(fast_interval="20s"):
            await asyncio.sleep(120)  # ensure update-status adds broker-capacities if missed

        # Assert that balancer is running and using certificates
        assert balancer_is_running(
            model_full_name=ops_test.model_full_name, app_name=self.balancer_app
        )
