#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

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
    SERIES,
    KRaftMode,
    KRaftUnitStatus,
    check_socket,
    create_test_topic,
    get_address,
    kraft_quorum_status,
)

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.kraft

CONTROLLER_APP = "controller"
PRODUCER_APP = "producer"


class TestKRaft:

    deployment_strat: str
    controller_app: str

    @pytest.fixture(autouse=True)
    def setup_method_fixture(self, kraft_mode: KRaftMode):
        self.deployment_strat = kraft_mode
        self.controller_app = {"single": APP_NAME, "multi": CONTROLLER_APP}[self.deployment_strat]

    async def _assert_listeners_accessible(
        self, ops_test: OpsTest, broker_unit_num=0, controller_unit_num=0
    ):
        logger.info(f"Asserting broker listeners are up: {APP_NAME}/{broker_unit_num}")
        address = await get_address(ops_test=ops_test, app_name=APP_NAME, unit_num=broker_unit_num)
        assert check_socket(
            address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].internal
        )  # Internal listener

        # Client listener should not be enabled if there is no relations
        assert not check_socket(
            address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client
        )

        logger.info(
            f"Asserting controller listeners are up: {self.controller_app}/{controller_unit_num}"
        )
        # Check controller socket
        if self.controller_app != APP_NAME:
            address = await get_address(
                ops_test=ops_test, app_name=self.controller_app, unit_num=controller_unit_num
            )

        assert check_socket(address, CONTROLLER_PORT)

    @pytest.mark.abort_on_fail
    @pytest.mark.skip_if_deployed
    async def test_build_and_deploy(self, ops_test: OpsTest, kafka_charm, kraft_mode):

        await asyncio.gather(
            ops_test.model.deploy(
                kafka_charm,
                application_name=APP_NAME,
                num_units=1,
                series=SERIES,
                config={
                    "roles": "broker,controller" if self.controller_app == APP_NAME else "broker",
                    "profile": "testing",
                },
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
                series=SERIES,
                config={
                    "roles": "controller",
                    "profile": "testing",
                },
                trust=True,
            )

        status = "active" if self.controller_app == APP_NAME else "blocked"
        await ops_test.model.wait_for_idle(
            apps=list({APP_NAME, self.controller_app}),
            idle_period=30,
            timeout=1800,
            raise_on_error=False,
            status=status,
        )

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

        async with ops_test.fast_forward(fast_interval="20s"):
            await asyncio.sleep(240)

        assert ops_test.model.applications[APP_NAME].status == "active"
        assert ops_test.model.applications[self.controller_app].status == "active"

    @pytest.mark.abort_on_fail
    async def test_listeners(self, ops_test: OpsTest):
        await self._assert_listeners_accessible(ops_test)

    @pytest.mark.abort_on_fail
    async def test_authorizer(self, ops_test: OpsTest):

        address = await get_address(ops_test=ops_test)
        port = SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].internal

        await create_test_topic(ops_test, f"{address}:{port}")

    @pytest.mark.abort_on_fail
    async def test_scale_out(self, ops_test: OpsTest):
        await ops_test.model.applications[self.controller_app].add_units(count=2)

        if self.deployment_strat == "multi":
            await ops_test.model.applications[APP_NAME].add_units(count=2)

        await ops_test.model.wait_for_idle(
            apps=list({APP_NAME, self.controller_app}),
            status="active",
            timeout=1200,
            idle_period=20,
            wait_for_exact_units=3,
        )

        address = await get_address(ops_test=ops_test, app_name=self.controller_app)
        bootstrap_controller = f"{address}:{CONTROLLER_PORT}"

        unit_status = kraft_quorum_status(
            ops_test, f"{self.controller_app}/0", bootstrap_controller
        )

        offset = KRAFT_NODE_ID_OFFSET if self.deployment_strat == "single" else 0

        for unit_id, status in unit_status.items():
            if unit_id == offset + 0:
                assert status == KRaftUnitStatus.LEADER
            elif unit_id < offset + 100:
                assert status == KRaftUnitStatus.FOLLOWER
            else:
                assert status == KRaftUnitStatus.OBSERVER

        for unit_num in range(3):
            await self._assert_listeners_accessible(
                ops_test, broker_unit_num=unit_num, controller_unit_num=unit_num
            )

    @pytest.mark.abort_on_fail
    async def test_leader_change(self, ops_test: OpsTest):
        await ops_test.model.applications[self.controller_app].destroy_units(
            f"{self.controller_app}/0"
        )
        await ops_test.model.wait_for_idle(
            apps=list({APP_NAME, self.controller_app}),
            status="active",
            timeout=600,
            idle_period=20,
        )

        # ensure proper cleanup
        async with ops_test.fast_forward(fast_interval="20s"):
            await asyncio.sleep(120)

        address = await get_address(ops_test=ops_test, app_name=self.controller_app, unit_num=1)
        bootstrap_controller = f"{address}:{CONTROLLER_PORT}"
        offset = KRAFT_NODE_ID_OFFSET if self.controller_app == APP_NAME else 0

        unit_status = kraft_quorum_status(
            ops_test, f"{self.controller_app}/1", bootstrap_controller
        )

        # assert new leader is elected
        assert (
            unit_status[offset + 1] == KRaftUnitStatus.LEADER
            or unit_status[offset + 2] == KRaftUnitStatus.LEADER
        )

        # test cluster stability by adding a new controller
        await ops_test.model.applications[self.controller_app].add_units(count=1)
        await ops_test.model.wait_for_idle(
            apps=list({APP_NAME, self.controller_app}),
            status="active",
            timeout=1200,
            idle_period=20,
        )

        # ensure unit is added to dynamic quorum
        async with ops_test.fast_forward(fast_interval="20s"):
            await asyncio.sleep(60)

        unit_status = kraft_quorum_status(
            ops_test, f"{self.controller_app}/1", bootstrap_controller
        )
        assert (offset + 3) in unit_status
        assert unit_status[offset + 3] == KRaftUnitStatus.FOLLOWER

    @pytest.mark.abort_on_fail
    async def test_scale_in(self, ops_test: OpsTest):
        await ops_test.model.applications[self.controller_app].destroy_units(
            *(f"{self.controller_app}/{unit_id}" for unit_id in (1, 2))
        )
        await ops_test.model.wait_for_idle(
            apps=[self.controller_app],
            status="active",
            timeout=600,
            idle_period=20,
            wait_for_exact_units=1,
        )

        async with ops_test.fast_forward(fast_interval="20s"):
            await asyncio.sleep(120)

        address = await get_address(ops_test=ops_test, app_name=self.controller_app, unit_num=3)
        bootstrap_controller = f"{address}:{CONTROLLER_PORT}"
        offset = KRAFT_NODE_ID_OFFSET if self.deployment_strat == "single" else 0

        unit_status = kraft_quorum_status(
            ops_test, f"{self.controller_app}/3", bootstrap_controller
        )

        assert unit_status[offset + 3] == KRaftUnitStatus.LEADER
        broker_unit_num = 3 if self.deployment_strat == "single" else 0
        await self._assert_listeners_accessible(
            ops_test, broker_unit_num=broker_unit_num, controller_unit_num=3
        )
