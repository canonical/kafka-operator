#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import time

import jubilant
import pytest
from single_kernel_kafka.core.literals import (
    INTERNAL_TLS_RELATION,
    KRAFT_NODE_ID_OFFSET,
    PEER_CLUSTER_ORCHESTRATOR_RELATION,
    PEER_CLUSTER_RELATION,
    SECURITY_PROTOCOL_PORTS,
)

from integration.k8s.helpers import TLS_CHANNEL, TLS_NAME
from integration.k8s.helpers.jubilant import all_active_idle, fast_forward
from integration.k8s.helpers.legacy import (
    APP_NAME,
    KAFKA_CONTAINER,
    KRaftMode,
    KRaftUnitStatus,
    create_test_topic,
    get_address,
    kraft_quorum_status,
    netcat,
    search_secrets,
)

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.kraft

CONTROLLER_APP = "controller"
CONTROLLER_PORT = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].controller
PRODUCER_APP = "producer"


class TestKRaft:

    deployment_strat: str
    controller_app: str
    tls_enabled: bool = os.environ.get("TLS", "disabled") == "enabled"

    @pytest.fixture(autouse=True)
    def setup_method_fixture(self, kraft_mode: KRaftMode):
        self.deployment_strat = kraft_mode
        self.controller_app = {"single": APP_NAME, "multi": CONTROLLER_APP}[self.deployment_strat]

    def _assert_broker_listeners_accessible(self, juju: jubilant.Juju, broker_unit_num=0):
        logger.info(f"Asserting broker listeners are up: {APP_NAME}/{broker_unit_num}")
        address = get_address(juju=juju, app_name=APP_NAME, unit_num=broker_unit_num)
        assert netcat(
            address, SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].internal
        )  # Internal listener

        # Client listener should not be enabled if there is no relations
        assert not netcat(
            address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client
        )

    def _assert_controller_listeners_accessible(self, juju: jubilant.Juju, controller_unit_num=0):
        # Check controller socket
        logger.info(
            f"Asserting controller listeners are up: {self.controller_app}/{controller_unit_num}"
        )
        address = get_address(
            juju=juju, app_name=self.controller_app, unit_num=controller_unit_num
        )

        assert netcat(address, CONTROLLER_PORT)

    def _assert_quorum_healthy(self, juju: jubilant.Juju):
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

    def test_build_and_deploy(self, juju: jubilant.Juju, kafka_charm):
        juju.deploy(
            kafka_charm,
            app=APP_NAME,
            num_units=1,
            config={
                "roles": "broker,controller" if self.controller_app == APP_NAME else "broker",
                "profile": "testing",
            },
            resources={"kafka-image": KAFKA_CONTAINER},
            trust=True,
        )
        juju.deploy(
            "kafka-test-app",
            app=PRODUCER_APP,
            channel="edge",
            num_units=1,
            base="ubuntu@22.04",
            config={
                "topic_name": "HOT-TOPIC",
                "num_messages": 100000,
                "role": "producer",
                "partitions": 20,
                "replication_factor": "1",
            },
            trust=True,
        )

        if self.controller_app != APP_NAME:
            juju.deploy(
                kafka_charm,
                app=self.controller_app,
                num_units=1,
                config={
                    "roles": self.controller_app,
                    "profile": "testing",
                },
                resources={"kafka-image": KAFKA_CONTAINER},
                trust=True,
            )

        status_check = all_active_idle if self.controller_app == APP_NAME else jubilant.all_blocked
        with fast_forward(juju, fast_interval="120s"):
            juju.wait(
                lambda status: status_check(status, *list({APP_NAME, self.controller_app})),
                successes=10,
                delay=3,
                timeout=1800,
            )

        # ensuring update-status fires
        with fast_forward(juju, fast_interval="10s"):
            time.sleep(30)

    def test_integrate(self, juju: jubilant.Juju):
        if self.controller_app != APP_NAME:
            juju.integrate(
                f"{APP_NAME}:{PEER_CLUSTER_ORCHESTRATOR_RELATION}",
                f"{CONTROLLER_APP}:{PEER_CLUSTER_RELATION}",
            )

        juju.wait(
            lambda status: all_active_idle(status, *list({APP_NAME, self.controller_app})),
            delay=3,
            successes=10,
            timeout=600,
        )

        with fast_forward(juju, fast_interval="60s"):
            time.sleep(120)

        status = juju.status()
        assert status.apps[APP_NAME].app_status.current == "active"
        assert status.apps[self.controller_app].app_status.current == "active"

    def test_listeners(self, juju: jubilant.Juju):
        print("SLEEPING")
        logger.info("SLEEPING")
        time.sleep(300)
        self._assert_broker_listeners_accessible(juju)
        self._assert_controller_listeners_accessible(juju)

    def test_authorizer(self, juju: jubilant.Juju):

        address = get_address(juju=juju)
        port = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].internal

        create_test_topic(juju, f"{address}:{port}")

    def test_scale_out(self, juju: jubilant.Juju):
        no_units = 2 if self.tls_enabled else 4
        juju.add_unit(self.controller_app, num_units=no_units)

        if self.deployment_strat == "multi":
            juju.add_unit(APP_NAME, num_units=2)

        with fast_forward(juju, fast_interval="120s"):
            juju.wait(
                lambda status: all_active_idle(status, *list({APP_NAME, self.controller_app})),
                delay=2,
                successes=20,
                timeout=3000,
            )

        address = get_address(juju=juju, app_name=self.controller_app)
        bootstrap_controller = f"{address}:{CONTROLLER_PORT}"

        unit_status = kraft_quorum_status(juju, f"{self.controller_app}/0", bootstrap_controller)

        offset = KRAFT_NODE_ID_OFFSET if self.controller_app == APP_NAME else 0

        for unit_id, status in unit_status.items():
            if unit_id < offset + 100:
                assert status in (KRaftUnitStatus.FOLLOWER, KRaftUnitStatus.LEADER)
            else:
                assert status == KRaftUnitStatus.OBSERVER

        for unit_num in range(3):
            self._assert_broker_listeners_accessible(juju, broker_unit_num=unit_num)

        for unit_num in range(no_units):
            self._assert_controller_listeners_accessible(juju, controller_unit_num=unit_num)

    @pytest.mark.skipif(tls_enabled, reason="Not required with TLS test.")
    def test_scale_in(self, juju: jubilant.Juju):
        juju.cli("scale-application", self.controller_app, "3")
        time.sleep(120)

        with fast_forward(juju, fast_interval="120s"):
            juju.wait(
                lambda status: len(status.apps[self.controller_app].units) == 3
                and all_active_idle(status, self.controller_app),
                delay=2,
                successes=20,
                timeout=1200,
            )

        address = get_address(juju=juju, app_name=self.controller_app, unit_num=0)
        bootstrap_controller = f"{address}:{CONTROLLER_PORT}"

        unit_status = kraft_quorum_status(juju, f"{self.controller_app}/0", bootstrap_controller)

        assert KRaftUnitStatus.LEADER in unit_status.values()

        for unit_num in range(3):
            self._assert_broker_listeners_accessible(juju, broker_unit_num=unit_num)
            self._assert_controller_listeners_accessible(juju, controller_unit_num=unit_num)

    @pytest.mark.skipif(not tls_enabled, reason="only required when TLS is on.")
    def test_relate_peer_tls(self, juju: jubilant.Juju):
        juju.deploy(TLS_NAME, app=TLS_NAME, channel=TLS_CHANNEL)
        juju.wait(
            lambda status: all_active_idle(status, TLS_NAME),
            delay=3,
            successes=10,
            timeout=600,
        )

        juju.integrate(f"{self.controller_app}:{INTERNAL_TLS_RELATION}", TLS_NAME)

        with fast_forward(juju, fast_interval="120s"):
            time.sleep(180)
            juju.wait(
                lambda status: all_active_idle(status, *{self.controller_app, APP_NAME, TLS_NAME}),
                delay=3,
                successes=15,
                timeout=2400,
            )

        for unit_num in range(3):
            self._assert_broker_listeners_accessible(juju, broker_unit_num=unit_num)
            self._assert_controller_listeners_accessible(juju, controller_unit_num=unit_num)

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

    @pytest.mark.skipif(not tls_enabled, reason="only required when TLS is on.")
    def test_remove_peer_tls_relation(self, juju: jubilant.Juju):
        juju.remove_relation(self.controller_app, TLS_NAME)

        with fast_forward(juju, fast_interval="120s"):
            time.sleep(180)
            juju.wait(
                lambda status: all_active_idle(status, *{self.controller_app, APP_NAME, TLS_NAME}),
                delay=3,
                successes=20,
                timeout=2400,
            )

        for unit_num in range(3):
            self._assert_broker_listeners_accessible(juju, broker_unit_num=unit_num)
            self._assert_controller_listeners_accessible(juju, controller_unit_num=unit_num)

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
