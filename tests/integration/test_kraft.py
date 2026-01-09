#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import time
from itertools import product

import jubilant
import pytest

from integration.ha.continuous_writes import ContinuousWrites
from integration.helpers import APP_NAME, DUMMY_NAME, REL_NAME_ADMIN
from integration.helpers.ha import assert_continuous_writes_consistency
from integration.helpers.jubilant import (
    BASE,
    KRaftMode,
    KRaftUnitStatus,
    all_active_idle,
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

    def _assert_listeners_accessible(
        self, juju: jubilant.Juju, broker_unit_num=0, controller_unit_num=0
    ):
        auth_map = AuthMap("SASL_SSL", "SCRAM-SHA-512")
        logger.info(f"Asserting broker listeners are up: {APP_NAME}/{broker_unit_num}")
        address = get_address(juju=juju, app_name=APP_NAME, unit_num=broker_unit_num)
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
            address = get_address(
                juju=juju, app_name=self.controller_app, unit_num=controller_unit_num
            )

        assert check_socket(address, SECURITY_PROTOCOL_PORTS[auth_map].controller)

    def _assert_quorum_healthy(self, juju: jubilant.Juju):
        address = get_address(juju=juju, app_name=self.controller_app)
        controller_port = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].controller
        bootstrap_controller = f"{address}:{controller_port}"

        unit_status = kraft_quorum_status(juju, f"{self.controller_app}/0", bootstrap_controller)

        offset = KRAFT_NODE_ID_OFFSET if self.deployment_strat == "single" else 0

        for unit_id, status in unit_status.items():
            if unit_id < offset + 100:
                assert status in (KRaftUnitStatus.FOLLOWER, KRaftUnitStatus.LEADER)
            else:
                assert status == KRaftUnitStatus.OBSERVER

    def test_build_and_deploy(self, juju: jubilant.Juju, kafka_charm, app_charm, kraft_mode):

        juju.deploy(
            kafka_charm,
            app=APP_NAME,
            num_units=1,
            base=BASE,
            config={
                "roles": "broker,controller" if self.controller_app == APP_NAME else "broker",
                "profile": "testing",
            },
            trust=True,
        )
        juju.deploy(
            app_charm,
            app=DUMMY_NAME,
            num_units=1,
            trust=True,
        )

        if self.controller_app != APP_NAME:
            juju.deploy(
                kafka_charm,
                app=self.controller_app,
                num_units=1,
                base=BASE,
                config={
                    "roles": "controller",
                    "profile": "testing",
                },
                trust=True,
            )

        assert_status_func = (
            jubilant.all_active if kraft_mode == "single" else jubilant.all_blocked
        )
        apps = [APP_NAME] if kraft_mode == "single" else [APP_NAME, self.controller_app]

        juju.wait(
            lambda status: jubilant.all_agents_idle(status, *apps)
            and assert_status_func(status, *apps),
            delay=3,
            successes=10,
            timeout=1800,
        )

    def test_integrate(self, juju: jubilant.Juju, kafka_apps):
        if self.controller_app != APP_NAME:
            juju.integrate(
                f"{APP_NAME}:{PEER_CLUSTER_ORCHESTRATOR_RELATION}",
                f"{CONTROLLER_APP}:{PEER_CLUSTER_RELATION}",
            )

        juju.wait(
            lambda status: all_active_idle(status, *kafka_apps),
            delay=3,
            successes=15,
            timeout=1800,
        )

        # Relate app with broker.
        juju.integrate(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")

        juju.wait(
            lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
            delay=3,
            successes=20,
            timeout=900,
        )

    def test_listeners(self, juju: jubilant.Juju):
        self._assert_listeners_accessible(juju)

    def test_authorizer(self, juju: jubilant.Juju):

        address = get_address(juju=juju)
        port = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].internal

        create_test_topic(juju, f"{address}:{port}")

    def test_scale_out(self, juju: jubilant.Juju):
        juju.add_unit(self.controller_app, num_units=2)

        if self.deployment_strat == "multi":
            juju.add_unit(APP_NAME, num_units=2)

        time.sleep(60)
        juju.wait(
            lambda status: all_active_idle(status, *list({APP_NAME, self.controller_app})),
            delay=3,
            successes=10,
            timeout=3000,
        )

        address = get_address(juju=juju, app_name=self.controller_app)
        controller_port = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].controller
        bootstrap_controller = f"{address}:{controller_port}"

        unit_status = kraft_quorum_status(juju, f"{self.controller_app}/0", bootstrap_controller)
        # Assert 1 leader
        assert len([s for s in unit_status.values() if s == KRaftUnitStatus.LEADER]) == 1

        offset = KRAFT_NODE_ID_OFFSET if self.deployment_strat == "single" else 0

        for unit_id, status in unit_status.items():
            if unit_id < offset + 100:
                assert status in (KRaftUnitStatus.FOLLOWER, KRaftUnitStatus.LEADER)
            else:
                assert status == KRaftUnitStatus.OBSERVER

        for unit_num in range(3):
            self._assert_listeners_accessible(
                juju, broker_unit_num=unit_num, controller_unit_num=unit_num
            )

    @pytest.mark.skipif(tls_enabled, reason="Not required with TLS test.")
    def test_leader_change(self, juju: jubilant.Juju):
        juju.remove_unit(f"{self.controller_app}/0")

        time.sleep(120)

        # ensure proper cleanup
        juju.wait(
            lambda status: all_active_idle(status, *list({APP_NAME, self.controller_app})),
            delay=3,
            successes=20,
            timeout=3000,
        )

        address = get_address(juju=juju, app_name=self.controller_app, unit_num=1)
        controller_port = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].controller
        bootstrap_controller = f"{address}:{controller_port}"
        offset = KRAFT_NODE_ID_OFFSET if self.controller_app == APP_NAME else 0

        unit_status = kraft_quorum_status(juju, f"{self.controller_app}/1", bootstrap_controller)

        # assert new leader is elected
        assert (
            unit_status[offset + 1] == KRaftUnitStatus.LEADER
            or unit_status[offset + 2] == KRaftUnitStatus.LEADER
        )

        # test cluster stability by adding a new controller
        juju.add_unit(self.controller_app, num_units=1)
        time.sleep(60)

        # ensure unit is added to dynamic quorum
        juju.wait(
            lambda status: all_active_idle(status, *list({APP_NAME, self.controller_app})),
            delay=3,
            successes=10,
            timeout=1200,
        )

        unit_status = kraft_quorum_status(juju, f"{self.controller_app}/1", bootstrap_controller)
        assert (offset + 3) in unit_status
        assert unit_status[offset + 3] == KRaftUnitStatus.FOLLOWER

    @pytest.mark.skipif(tls_enabled, reason="Not required with TLS test.")
    def test_scale_in(self, juju: jubilant.Juju):
        for unit_id in (1, 2):
            juju.remove_unit(f"{self.controller_app}/{unit_id}")

        time.sleep(120)

        juju.wait(
            lambda status: all_active_idle(status, *list({APP_NAME, self.controller_app})),
            delay=3,
            successes=15,
            timeout=1200,
        )

        address = get_address(juju=juju, app_name=self.controller_app, unit_num=3)
        controller_port = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].controller
        bootstrap_controller = f"{address}:{controller_port}"
        offset = KRAFT_NODE_ID_OFFSET if self.deployment_strat == "single" else 0

        unit_status = kraft_quorum_status(juju, f"{self.controller_app}/3", bootstrap_controller)

        assert unit_status[offset + 3] == KRaftUnitStatus.LEADER
        broker_unit_num = 3 if self.deployment_strat == "single" else 0
        self._assert_listeners_accessible(
            juju, broker_unit_num=broker_unit_num, controller_unit_num=3
        )

    @pytest.mark.skipif(not tls_enabled, reason="only required when TLS is on.")
    def test_relate_peer_tls(self, juju: jubilant.Juju):
        # This test and the following one are inherently long due to double rolling restarts,
        # In order not to break on constrained CI, we decrease the produce rate of CW to 2/s.
        c_writes = ContinuousWrites(model=juju.model, app=DUMMY_NAME, produce_rate=2)
        c_writes.start()

        juju.deploy(TLS_NAME, app=TLS_NAME, channel="1/stable")
        juju.wait(
            lambda status: all_active_idle(status, TLS_NAME),
            delay=3,
            successes=10,
            timeout=600,
        )

        juju.integrate(f"{self.controller_app}:{INTERNAL_TLS_RELATION}", TLS_NAME)

        juju.wait(
            lambda status: all_active_idle(status, self.controller_app, TLS_NAME),
            delay=3,
            successes=15,
            timeout=2400,
        )

        for unit_num in range(3):
            self._assert_listeners_accessible(
                juju, broker_unit_num=unit_num, controller_unit_num=unit_num
            )

        # Check quorum is healthy
        self._assert_quorum_healthy(juju)

        internal_ca = search_secrets(juju, owner=self.controller_app, search_key="internal-ca")
        controller_ca = search_secrets(
            juju, owner=f"{self.controller_app}/0", search_key="peer-ca-cert"
        )

        assert internal_ca
        assert controller_ca
        # ensure we're not using internal CA
        assert internal_ca != controller_ca

        results = c_writes.stop()
        assert_continuous_writes_consistency(results)

    @pytest.mark.skipif(not tls_enabled, reason="only required when TLS is on.")
    def test_remove_peer_tls_relation(self, juju: jubilant.Juju):
        c_writes = ContinuousWrites(model=juju.model, app=DUMMY_NAME, produce_rate=2)
        c_writes.start()
        time.sleep(60)

        juju.remove_relation(self.controller_app, TLS_NAME)

        juju.wait(
            lambda status: all_active_idle(status, self.controller_app, TLS_NAME),
            delay=3,
            successes=20,
            timeout=2400,
        )

        for unit_num in range(3):
            self._assert_listeners_accessible(
                juju, broker_unit_num=unit_num, controller_unit_num=unit_num
            )

        # Check quorum is healthy
        self._assert_quorum_healthy(juju)

        internal_ca = search_secrets(juju, owner=self.controller_app, search_key="internal-ca")
        controller_ca = search_secrets(
            juju, owner=f"{self.controller_app}/0", search_key="peer-ca-cert"
        )

        assert internal_ca
        assert controller_ca
        # Now we should be using internal CA
        assert internal_ca == controller_ca

        results = c_writes.stop()
        assert_continuous_writes_consistency(results)

        # Wait for a couple of update-statues
        juju.cli("model-config", "update-status-hook-interval=60s")
        time.sleep(300)

        # We should have no temporary alias in the truststore
        for i, app in product(range(3), {APP_NAME, self.controller_app}):
            aliases = list_truststore_aliases(juju, f"{app}/{i}", scope="peer")
            logger.info(f"Trust aliases in {app}/{i}: {aliases}")
            assert not ([alias for alias in aliases if "old-" in alias or "new-" in alias])
