#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import os
from itertools import product

import pytest
from pytest_operator.plugin import OpsTest

from integration.ha.continuous_writes import ContinuousWrites
from integration.helpers.ha import assert_continuous_writes_consistency
from integration.helpers.pytest_operator import (
    APP_NAME,
    DUMMY_NAME,
    REL_NAME_ADMIN,
    SERIES,
    KRaftMode,
    check_socket,
    create_test_topic,
    get_address,
    kraft_quorum_status,
    list_truststore_aliases,
    search_secrets,
)
from literals import (
    INTERNAL_TLS_RELATION,
    KRAFT_NODE_ID_OFFSET,
    PEER_CLUSTER_ORCHESTRATOR_RELATION,
    PEER_CLUSTER_RELATION,
    SECURITY_PROTOCOL_PORTS,
    AuthMap,
    KRaftUnitStatus,
)

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.kraft

CONTROLLER_APP = "controller"
TLS_NAME = "self-signed-certificates"


class TestKRaft:

    deployment_strat: str
    controller_app: str
    tls_enabled: bool = os.environ.get("TLS", "disabled") == "enabled"

    @pytest.fixture(autouse=True)
    def setup_method_fixture(self, kraft_mode: KRaftMode):
        self.deployment_strat = kraft_mode
        self.controller_app = {"single": APP_NAME, "multi": CONTROLLER_APP}[self.deployment_strat]

    async def _assert_listeners_accessible(
        self, ops_test: OpsTest, broker_unit_num=0, controller_unit_num=0
    ):
        auth_map = AuthMap("SASL_SSL", "SCRAM-SHA-512")
        logger.info(f"Asserting broker listeners are up: {APP_NAME}/{broker_unit_num}")
        address = await get_address(ops_test=ops_test, app_name=APP_NAME, unit_num=broker_unit_num)
        assert check_socket(
            address, SECURITY_PROTOCOL_PORTS[auth_map].internal
        )  # Internal listener

        # Client listener should not be enabled if there is no relations
        assert not check_socket(address, SECURITY_PROTOCOL_PORTS[auth_map].client)

        logger.info(
            f"Asserting controller listeners are up: {self.controller_app}/{controller_unit_num}"
        )
        # Check controller socket
        if self.controller_app != APP_NAME:
            address = await get_address(
                ops_test=ops_test, app_name=self.controller_app, unit_num=controller_unit_num
            )

        assert check_socket(address, SECURITY_PROTOCOL_PORTS[auth_map].controller)

    async def _assert_quorum_healthy(self, ops_test: OpsTest):
        address = await get_address(ops_test=ops_test, app_name=self.controller_app)
        controller_port = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].controller
        bootstrap_controller = f"{address}:{controller_port}"

        unit_status = kraft_quorum_status(
            ops_test, f"{self.controller_app}/0", bootstrap_controller
        )

        offset = KRAFT_NODE_ID_OFFSET if self.deployment_strat == "single" else 0

        for unit_id, status in unit_status.items():
            if unit_id < offset + 100:
                assert status in (KRaftUnitStatus.FOLLOWER, KRaftUnitStatus.LEADER)
            else:
                assert status == KRaftUnitStatus.OBSERVER

    @pytest.mark.abort_on_fail
    @pytest.mark.skip_if_deployed
    async def test_build_and_deploy(self, ops_test: OpsTest, kafka_charm, app_charm, kraft_mode):

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
                app_charm,
                application_name=DUMMY_NAME,
                series=SERIES,
                num_units=1,
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
    async def test_integrate(self, ops_test: OpsTest, kafka_apps):
        if self.controller_app != APP_NAME:
            await ops_test.model.add_relation(
                f"{APP_NAME}:{PEER_CLUSTER_ORCHESTRATOR_RELATION}",
                f"{CONTROLLER_APP}:{PEER_CLUSTER_RELATION}",
            )

        async with ops_test.fast_forward(fast_interval="60s"):
            await ops_test.model.wait_for_idle(
                apps={self.controller_app, APP_NAME},
                idle_period=40,
                timeout=1800,
                status="active",
            )

        assert ops_test.model.applications[APP_NAME].status == "active"
        assert ops_test.model.applications[self.controller_app].status == "active"

        # Relate app with broker.
        await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
        await ops_test.model.wait_for_idle(
            apps=[*kafka_apps, DUMMY_NAME], idle_period=60, status="active"
        )

    @pytest.mark.abort_on_fail
    async def test_listeners(self, ops_test: OpsTest):
        await self._assert_listeners_accessible(ops_test)

    @pytest.mark.abort_on_fail
    async def test_authorizer(self, ops_test: OpsTest):

        address = await get_address(ops_test=ops_test)
        port = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].internal

        await create_test_topic(ops_test, f"{address}:{port}")

    @pytest.mark.abort_on_fail
    async def test_scale_out(self, ops_test: OpsTest):
        await ops_test.model.applications[self.controller_app].add_units(count=2)

        if self.deployment_strat == "multi":
            await ops_test.model.applications[APP_NAME].add_units(count=2)

        await ops_test.model.wait_for_idle(
            apps=list({APP_NAME, self.controller_app}),
            status="active",
            timeout=1800,
            idle_period=20,
            raise_on_error=False,
            wait_for_exact_units=3,
        )

        address = await get_address(ops_test=ops_test, app_name=self.controller_app)
        controller_port = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].controller
        bootstrap_controller = f"{address}:{controller_port}"

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
    @pytest.mark.skipif(tls_enabled, reason="Not required with TLS test.")
    async def test_leader_change(self, ops_test: OpsTest):
        await ops_test.model.applications[self.controller_app].destroy_units(
            f"{self.controller_app}/0"
        )

        await asyncio.sleep(120)

        # ensure proper cleanup
        async with ops_test.fast_forward(fast_interval="60s"):
            await ops_test.model.wait_for_idle(
                apps=list({APP_NAME, self.controller_app}),
                status="active",
                timeout=1800,
                idle_period=40,
            )

        address = await get_address(ops_test=ops_test, app_name=self.controller_app, unit_num=1)
        controller_port = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].controller
        bootstrap_controller = f"{address}:{controller_port}"
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

        # ensure unit is added to dynamic quorum
        async with ops_test.fast_forward(fast_interval="120s"):
            await ops_test.model.wait_for_idle(
                apps=list({APP_NAME, self.controller_app}),
                status="active",
                timeout=1200,
                idle_period=30,
            )

        unit_status = kraft_quorum_status(
            ops_test, f"{self.controller_app}/1", bootstrap_controller
        )
        assert (offset + 3) in unit_status
        assert unit_status[offset + 3] == KRaftUnitStatus.FOLLOWER

    @pytest.mark.abort_on_fail
    @pytest.mark.skipif(tls_enabled, reason="Not required with TLS test.")
    async def test_scale_in(self, ops_test: OpsTest):
        await ops_test.model.applications[self.controller_app].destroy_units(
            *(f"{self.controller_app}/{unit_id}" for unit_id in (1, 2))
        )

        await asyncio.sleep(120)

        async with ops_test.fast_forward(fast_interval="60s"):
            await ops_test.model.wait_for_idle(
                apps=[self.controller_app],
                status="active",
                timeout=1200,
                idle_period=40,
                wait_for_exact_units=1,
            )

        address = await get_address(ops_test=ops_test, app_name=self.controller_app, unit_num=3)
        controller_port = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].controller
        bootstrap_controller = f"{address}:{controller_port}"
        offset = KRAFT_NODE_ID_OFFSET if self.deployment_strat == "single" else 0

        unit_status = kraft_quorum_status(
            ops_test, f"{self.controller_app}/3", bootstrap_controller
        )

        assert unit_status[offset + 3] == KRaftUnitStatus.LEADER
        broker_unit_num = 3 if self.deployment_strat == "single" else 0
        await self._assert_listeners_accessible(
            ops_test, broker_unit_num=broker_unit_num, controller_unit_num=3
        )

    @pytest.mark.skipif(not tls_enabled, reason="only required when TLS is on.")
    @pytest.mark.abort_on_fail
    async def test_relate_peer_tls(self, ops_test: OpsTest):
        # This test and the following one are inherently long due to double rolling restarts,
        # In order not to break on constrained CI, we decrease the produce rate of CW to 2/s.
        c_writes = ContinuousWrites(model=ops_test.model_full_name, app=DUMMY_NAME, produce_rate=2)
        c_writes.start()

        await ops_test.model.deploy(TLS_NAME, application_name=TLS_NAME, channel="1/stable")
        await ops_test.model.wait_for_idle(
            apps=[TLS_NAME], idle_period=30, timeout=600, status="active"
        )

        await ops_test.model.add_relation(
            f"{self.controller_app}:{INTERNAL_TLS_RELATION}", TLS_NAME
        )

        async with ops_test.fast_forward(fast_interval="120s"):
            await ops_test.model.wait_for_idle(
                apps={self.controller_app, APP_NAME, TLS_NAME},
                idle_period=45,
                timeout=2400,
                status="active",
            )

        for unit_num in range(3):
            await self._assert_listeners_accessible(
                ops_test, broker_unit_num=unit_num, controller_unit_num=unit_num
            )

        # Check quorum is healthy
        await self._assert_quorum_healthy(ops_test)

        internal_ca = search_secrets(ops_test, owner=self.controller_app, search_key="internal-ca")
        controller_ca = search_secrets(
            ops_test, owner=f"{self.controller_app}/0", search_key="peer-ca-cert"
        )

        assert internal_ca
        assert controller_ca
        # ensure we're not using internal CA
        assert internal_ca != controller_ca

        results = c_writes.stop()
        assert_continuous_writes_consistency(results)

    @pytest.mark.skipif(not tls_enabled, reason="only required when TLS is on.")
    @pytest.mark.abort_on_fail
    async def test_remove_peer_tls_relation(self, ops_test: OpsTest):
        c_writes = ContinuousWrites(model=ops_test.model_full_name, app=DUMMY_NAME, produce_rate=2)
        c_writes.start()
        await asyncio.sleep(60)

        await ops_test.juju("remove-relation", self.controller_app, TLS_NAME)

        async with ops_test.fast_forward(fast_interval="120s"):
            await ops_test.model.wait_for_idle(
                apps={self.controller_app, APP_NAME, TLS_NAME},
                idle_period=60,
                timeout=2400,
                status="active",
            )

        for unit_num in range(3):
            await self._assert_listeners_accessible(
                ops_test, broker_unit_num=unit_num, controller_unit_num=unit_num
            )

        # Check quorum is healthy
        await self._assert_quorum_healthy(ops_test)

        internal_ca = search_secrets(ops_test, owner=self.controller_app, search_key="internal-ca")
        controller_ca = search_secrets(
            ops_test, owner=f"{self.controller_app}/0", search_key="peer-ca-cert"
        )

        assert internal_ca
        assert controller_ca
        # Now we should be using internal CA
        assert internal_ca == controller_ca

        results = c_writes.stop()
        assert_continuous_writes_consistency(results)

        async with ops_test.fast_forward(fast_interval="60s"):
            # Wait for a couple of update-statues
            await asyncio.sleep(300)

        # We should have no temporary alias in the truststore
        for i, app in product(range(3), {APP_NAME, self.controller_app}):
            aliases = await list_truststore_aliases(ops_test, f"{app}/{i}", scope="peer")
            logger.info(f"Trust aliases in {app}/{i}: {aliases}")
            assert not ([alias for alias in aliases if "old-" in alias or "new-" in alias])
