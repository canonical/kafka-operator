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
    PEER_CLUSTER_ORCHESTRATOR_RELATION,
    PEER_CLUSTER_RELATION,
    SECURITY_PROTOCOL_PORTS,
)

from .helpers import (
    APP_NAME,
    check_socket,
    get_address,
)

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.kraft

CONTROLLER_APP = "controller"
PRODUCER_APP = "producer"


class TestKRaft:

    deployment_strat: str = os.environ.get("DEPLOYMENT", "multi")
    controller_app: str = {"single": APP_NAME, "multi": CONTROLLER_APP}[deployment_strat]

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
                series="jammy",
                config={
                    "roles": self.controller_app,
                    "profile": "testing",
                },
                trust=True,
            )

        await ops_test.model.wait_for_idle(
            apps=list({APP_NAME, self.controller_app}),
            idle_period=30,
            timeout=1800,
            raise_on_error=False,
        )
        if self.controller_app != APP_NAME:
            assert ops_test.model.applications[APP_NAME].status == "blocked"
            assert ops_test.model.applications[self.controller_app].status == "blocked"
        else:
            assert ops_test.model.applications[APP_NAME].status == "active"

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
        address = await get_address(ops_test=ops_test)
        assert check_socket(
            address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].internal
        )  # Internal listener

        # Client listener should not be enabled if there is no relations
        assert not check_socket(
            address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client
        )

        # Check controller socket
        if self.controller_app != APP_NAME:
            address = await get_address(ops_test=ops_test, app_name=self.controller_app)

        assert check_socket(address, CONTROLLER_PORT)
