#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import os

import pytest
from pytest_operator.plugin import OpsTest

from literals import (
    CONTROLLER_PORT,
    KRAFT_NODE_ID_OFFSET,
    PEER_CLUSTER_ORCHESTRATOR_RELATION,
    PEER_CLUSTER_RELATION,
    SECURITY_PROTOCOL_PORTS,
)

from .helpers import (
    APP_NAME,
    KAFKA_CONTAINER,
    KRaftUnitStatus,
    create_test_topic,
    get_address,
    kraft_quorum_status,
    netcat,
)

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.kraft

CONTROLLER_APP = "controller"
PRODUCER_APP = "producer"


class TestKRaft:

    deployment_strat: str = os.environ.get("DEPLOYMENT", "multi")
    controller_app: str = {"single": APP_NAME, "multi": CONTROLLER_APP}[deployment_strat]

    async def _assert_broker_listeners_accessible(self, ops_test: OpsTest, broker_unit_num=0):
        logger.info(f"Asserting broker listeners are up: {APP_NAME}/{broker_unit_num}")
        address = await get_address(ops_test=ops_test, app_name=APP_NAME, unit_num=broker_unit_num)
        assert netcat(
            address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].internal
        )  # Internal listener

        # Client listener should not be enabled if there is no relations
        assert not netcat(
            address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client
        )

    async def _assert_controller_listeners_accessible(
        self, ops_test: OpsTest, controller_unit_num=0
    ):
        # Check controller socket
        logger.info(
            f"Asserting controller listeners are up: {self.controller_app}/{controller_unit_num}"
        )
        address = await get_address(
            ops_test=ops_test, app_name=self.controller_app, unit_num=controller_unit_num
        )

        assert netcat(address, CONTROLLER_PORT)

    @pytest.mark.abort_on_fail
    async def test_build_and_deploy(self, ops_test: OpsTest, kafka_charm):
        await asyncio.gather(
            ops_test.model.deploy(
                kafka_charm,
                application_name=APP_NAME,
                num_units=1,
                series="jammy",
                config={
                    "roles": "broker,controller" if self.controller_app == APP_NAME else "broker",
                    "profile": "testing",
                },
                resources={"kafka-image": KAFKA_CONTAINER},
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
                    "replication_factor": "1",
                },
                trust=True,
            ),
        )

        if self.controller_app != APP_NAME:
            await ops_test.model.deploy(
                kafka_charm,
                application_name=self.controller_app,
                num_units=1,
                series="jammy",
                config={
                    "roles": self.controller_app,
                    "profile": "testing",
                },
                resources={"kafka-image": KAFKA_CONTAINER},
                trust=True,
            )

        status = "active" if self.controller_app == APP_NAME else "blocked"
        async with ops_test.fast_forward(fast_interval="60s"):
            await ops_test.model.wait_for_idle(
                apps=list({APP_NAME, self.controller_app}),
                idle_period=30,
                timeout=1800,
                raise_on_error=False,
                status=status,
            )

        # ensuring update-status fires
        async with ops_test.fast_forward(fast_interval="10s"):
            await asyncio.sleep(30)

    @pytest.mark.abort_on_fail
    async def test_integrate(self, ops_test: OpsTest):
        if self.controller_app != APP_NAME:
            await ops_test.model.add_relation(
                f"{APP_NAME}:{PEER_CLUSTER_ORCHESTRATOR_RELATION}",
                f"{CONTROLLER_APP}:{PEER_CLUSTER_RELATION}",
            )

        await ops_test.model.wait_for_idle(
            apps=list({APP_NAME, self.controller_app}), idle_period=30
        )

        async with ops_test.fast_forward(fast_interval="40s"):
            await asyncio.sleep(120)

        assert ops_test.model.applications[APP_NAME].status == "active"
        assert ops_test.model.applications[self.controller_app].status == "active"

    @pytest.mark.abort_on_fail
    async def test_listeners(self, ops_test: OpsTest):
        print("SLEEPING")
        logger.info("SLEEPING")
        await asyncio.sleep(300)
        await self._assert_broker_listeners_accessible(ops_test)
        await self._assert_controller_listeners_accessible(ops_test)

    @pytest.mark.abort_on_fail
    async def test_authorizer(self, ops_test: OpsTest):

        address = await get_address(ops_test=ops_test)
        port = SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].internal

        await create_test_topic(ops_test, f"{address}:{port}")

    @pytest.mark.abort_on_fail
    async def test_scale_out(self, ops_test: OpsTest):
        await ops_test.model.applications[self.controller_app].add_units(count=4)

        if self.deployment_strat == "multi":
            await ops_test.model.applications[APP_NAME].add_units(count=2)

        await ops_test.model.wait_for_idle(
            apps=list({APP_NAME, self.controller_app}),
            status="active",
            timeout=1200,
            idle_period=20,
        )

        address = await get_address(ops_test=ops_test, app_name=self.controller_app)
        bootstrap_controller = f"{address}:{CONTROLLER_PORT}"

        unit_status = kraft_quorum_status(
            ops_test, f"{self.controller_app}/0", bootstrap_controller
        )

        offset = KRAFT_NODE_ID_OFFSET if self.controller_app == APP_NAME else 0

        for unit_id, status in unit_status.items():
            if unit_id == offset + 0:
                assert status == KRaftUnitStatus.LEADER
            elif unit_id < offset + 100:
                assert status == KRaftUnitStatus.FOLLOWER
            else:
                assert status == KRaftUnitStatus.OBSERVER

        for unit_num in range(3):
            await self._assert_broker_listeners_accessible(ops_test, broker_unit_num=unit_num)

        for unit_num in range(5):
            await self._assert_controller_listeners_accessible(
                ops_test, controller_unit_num=unit_num
            )

    @pytest.mark.abort_on_fail
    async def test_scale_in(self, ops_test: OpsTest):
        await ops_test.model.applications[self.controller_app].scale(scale=3)
        await ops_test.model.wait_for_idle(
            apps=[self.controller_app],
            status="active",
            timeout=600,
            idle_period=20,
            wait_for_exact_units=3,
        )

        async with ops_test.fast_forward(fast_interval="30s"):
            await asyncio.sleep(120)

        address = await get_address(ops_test=ops_test, app_name=self.controller_app, unit_num=0)
        bootstrap_controller = f"{address}:{CONTROLLER_PORT}"

        unit_status = kraft_quorum_status(
            ops_test, f"{self.controller_app}/0", bootstrap_controller
        )

        assert KRaftUnitStatus.LEADER in unit_status.values()

        for unit_num in range(3):
            await self._assert_broker_listeners_accessible(ops_test, broker_unit_num=unit_num)
            await self._assert_controller_listeners_accessible(
                ops_test, controller_unit_num=unit_num
            )
