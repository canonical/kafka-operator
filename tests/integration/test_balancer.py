#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import time
from subprocess import CalledProcessError

import jubilant
import pytest
from tenacity import Retrying, stop_after_attempt, wait_fixed

from integration.helpers.jubilant import (
    APP_NAME,
    BASE,
    CONTROLLER_NAME,
    all_active_idle,
    balancer_exporter_is_up,
    balancer_is_ready,
    balancer_is_running,
    balancer_is_secure,
    get_replica_count_by_broker_id,
)
from literals import (
    INTERNAL_TLS_RELATION,
    PEER_CLUSTER_ORCHESTRATOR_RELATION,
    PEER_CLUSTER_RELATION,
)

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.balancer

PRODUCER_APP = "producer"
TLS_NAME = "self-signed-certificates"


class TestBalancer:

    deployment_strat: str = os.environ.get("DEPLOYMENT", "multi")
    balancer_app: str = {"single": APP_NAME, "multi": CONTROLLER_NAME}[deployment_strat]

    def test_build_and_deploy(self, juju: jubilant.Juju, kafka_charm):

        juju.deploy(
            kafka_charm,
            app=APP_NAME,
            num_units=1,
            base=BASE,
            config={
                "roles": "broker,balancer" if self.balancer_app == APP_NAME else "broker",
                "profile": "testing",
            },
            trust=True,
        )
        juju.deploy(
            kafka_charm,
            app=CONTROLLER_NAME,
            num_units=1,
            base=BASE,
            trust=True,
            config={
                "roles": "controller" if self.balancer_app == APP_NAME else "controller,balancer",
                "profile": "testing",
            },
        )
        juju.deploy(
            "kafka-test-app",
            app=PRODUCER_APP,
            channel="edge",
            num_units=1,
            config={
                "topic_name": "HOT-TOPIC",
                "num_messages": 100000,
                "role": "producer",
                "partitions": 20,
                "replication_factor": "3",
            },
            trust=True,
        )

        juju.wait(
            lambda status: jubilant.all_agents_idle(
                status, *list({APP_NAME, CONTROLLER_NAME, self.balancer_app})
            ),
            delay=3,
            successes=10,
            timeout=1200,
        )

        # ensuring update-status fires
        juju.cli("model-config", "update-status-hook-interval=60s")
        time.sleep(90)

        status = juju.status()
        assert status.apps[APP_NAME].app_status.current == "blocked"
        assert status.apps[CONTROLLER_NAME].app_status.current == "blocked"
        assert status.apps[self.balancer_app].app_status.current == "blocked"

    def test_relate_not_enough_brokers(self, juju: jubilant.Juju):
        juju.integrate(
            f"{APP_NAME}:{PEER_CLUSTER_ORCHESTRATOR_RELATION}",
            f"{CONTROLLER_NAME}:{PEER_CLUSTER_RELATION}",
        )
        juju.integrate(PRODUCER_APP, APP_NAME)

        juju.wait(
            lambda status: jubilant.all_agents_idle(
                status, *list({APP_NAME, CONTROLLER_NAME, self.balancer_app})
            ),
            delay=3,
            successes=10,
            timeout=1200,
        )

        time.sleep(180)  # ensure update-status adds broker-capacities if missed

        assert juju.status().apps[self.balancer_app].app_status.current == "waiting"

        with pytest.raises(CalledProcessError):
            assert balancer_is_running(model_full_name=juju.model, app_name=self.balancer_app)

    def test_minimum_brokers_balancer_starts(self, juju: jubilant.Juju):
        juju.add_unit(APP_NAME, num_units=2)
        time.sleep(60)

        juju.wait(
            lambda status: all_active_idle(
                status, *list({APP_NAME, CONTROLLER_NAME, self.balancer_app, PRODUCER_APP})
            ),
            delay=3,
            successes=20,
            timeout=3600,
        )

        assert balancer_is_running(model_full_name=juju.model, app_name=self.balancer_app)
        assert balancer_is_secure(juju, app_name=self.balancer_app)

    def test_balancer_exporter_endpoints(self, juju: jubilant.Juju):
        assert balancer_exporter_is_up(juju.model, self.balancer_app)

    def test_balancer_monitor_state(self, juju: jubilant.Juju):
        assert balancer_is_ready(juju=juju, app_name=self.balancer_app)

    @pytest.mark.skipif(
        deployment_strat == "single", reason="Testing full rebalance on large deployment"
    )
    def test_add_unit_full_rebalance(self, juju: jubilant.Juju):
        juju.add_unit(APP_NAME, num_units=1)  # up to 4, new unit won't have any partitions
        time.sleep(60)

        juju.wait(
            lambda status: all_active_idle(
                status, *list({APP_NAME, CONTROLLER_NAME, self.balancer_app, PRODUCER_APP})
            ),
            delay=3,
            successes=10,
            timeout=1800,
        )

        time.sleep(120)  # ensure update-status adds broker-capacities if missed

        assert balancer_is_ready(juju=juju, app_name=self.balancer_app)

        # verify CC can find the new broker_id 3
        broker_replica_count = get_replica_count_by_broker_id(juju, self.balancer_app)
        new_broker_id = max(map(int, broker_replica_count.keys()))

        for unit, unit_status in juju.status().apps[self.balancer_app].units.items():
            if unit_status.leader:
                leader_unit = unit

        response = juju.run(leader_unit, "rebalance", params={"mode": "full", "dryrun": False})
        assert not response.results.get("error", "")

        assert int(
            get_replica_count_by_broker_id(juju, self.balancer_app).get(str(new_broker_id), 0)
        )  # replicas were successfully moved

    @pytest.mark.skipif(
        deployment_strat == "multi", reason="Testing full rebalance on single-app deployment"
    )
    def test_add_unit_targeted_rebalance(self, juju: jubilant.Juju):
        assert balancer_is_ready(juju=juju, app_name=self.balancer_app)
        juju.add_unit(APP_NAME, num_units=1)  # up to 4, new unit won't have any partitions
        time.sleep(60)

        juju.wait(
            lambda status: all_active_idle(
                status, *list({APP_NAME, CONTROLLER_NAME, self.balancer_app, PRODUCER_APP})
            ),
            delay=3,
            successes=10,
            timeout=1800,
        )

        time.sleep(120)  # ensure update-status adds broker-capacities if missed

        assert balancer_is_ready(juju=juju, app_name=self.balancer_app)

        # verify CC can find the new broker_id 3
        broker_replica_count = get_replica_count_by_broker_id(juju, self.balancer_app)
        new_broker_id = max(map(int, broker_replica_count.keys()))

        for unit, unit_status in juju.status().apps[self.balancer_app].units.items():
            if unit_status.leader:
                leader_unit = unit

        time.sleep(120)  # Give CC some room to breathe before making other API calls
        assert balancer_is_ready(juju=juju, app_name=self.balancer_app)
        response = juju.run(
            leader_unit,
            "rebalance",
            params={"mode": "add", "brokerid": new_broker_id, "dryrun": False},
        )

        assert not response.results.get("error", "")

        # New broker has partition(s)
        assert int(
            get_replica_count_by_broker_id(juju, self.balancer_app).get(str(new_broker_id), 0)
        )  # replicas were successfully moved

    @pytest.mark.skipif(
        deployment_strat == "multi", reason="Testing full rebalance on single-app deployment"
    )
    def test_balancer_prepare_unit_removal(self, juju: jubilant.Juju):
        assert balancer_is_ready(juju=juju, app_name=self.balancer_app)
        broker_replica_count = get_replica_count_by_broker_id(juju, self.balancer_app)
        new_broker_id = max(map(int, broker_replica_count.keys()))

        # storing the current replica counts of 0, 1, 2 - they will persist
        pre_rebalance_replica_counts = {
            key: value
            for key, value in get_replica_count_by_broker_id(juju, self.balancer_app).items()
            if key != str(new_broker_id)
        }

        for unit, unit_status in juju.status().apps[self.balancer_app].units.items():
            if unit_status.leader:
                leader_unit = unit

        assert balancer_is_ready(juju=juju, app_name=self.balancer_app)

        for attempt in Retrying(stop=stop_after_attempt(5), wait=wait_fixed(60), reraise=True):
            with attempt:
                response = juju.run(
                    leader_unit,
                    "rebalance",
                    params={"mode": "remove", "brokerid": new_broker_id, "dryrun": False},
                )
                assert not response.results.get("error", "")

        post_rebalance_replica_counts = get_replica_count_by_broker_id(juju, self.balancer_app)

        # Partition only were moved from the removed broker to the other ones
        for existing_broker, previous_replica_count in pre_rebalance_replica_counts.items():
            assert previous_replica_count <= post_rebalance_replica_counts.get(
                str(existing_broker)
            )

        # Replicas were successfully moved
        assert not int(
            get_replica_count_by_broker_id(juju, self.balancer_app).get(str(new_broker_id), 0)
        )

    def test_tls(self, juju: jubilant.Juju):
        # deploy and integrate tls
        tls_config = {"ca-common-name": "kafka"}

        juju.deploy(TLS_NAME, channel="1/stable", config=tls_config)

        juju.wait(
            lambda status: all_active_idle(status, TLS_NAME),
            delay=3,
            successes=10,
            timeout=900,
        )

        assert juju.status().apps[TLS_NAME].app_status.current == "active"

        juju.integrate(TLS_NAME, f"{APP_NAME}:{INTERNAL_TLS_RELATION}")

        if self.balancer_app != APP_NAME:
            juju.integrate(TLS_NAME, f"{self.balancer_app}:{INTERNAL_TLS_RELATION}")

        juju.wait(
            lambda status: all_active_idle(status, *list({APP_NAME, CONTROLLER_NAME, TLS_NAME})),
            delay=3,
            successes=10,
            timeout=3600,
        )

        time.sleep(120)  # ensure update-status adds broker-capacities if missed

        # Assert that balancer is running and using certificates
        assert balancer_is_running(model_full_name=juju.model, app_name=self.balancer_app)
