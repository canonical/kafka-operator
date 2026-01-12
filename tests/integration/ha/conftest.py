#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import subprocess
import time
from itertools import product

import jubilant
import pytest

from integration.ha.continuous_writes import ContinuousWrites
from integration.helpers import (
    APP_NAME,
)
from integration.helpers.ha import (
    RESTART_DELAY,
    assert_all_brokers_up,
    network_release,
    network_restore,
    patch_restart_delay,
    remove_restart_delay,
    reset_kafka_service,
)

logger = logging.getLogger(__name__)


@pytest.fixture()
def c_writes(juju: jubilant.Juju):
    """Creates instance of the ContinuousWrites."""
    app = APP_NAME
    assert juju.model
    return ContinuousWrites(juju.model, app)


@pytest.fixture()
def c_writes_runner(c_writes: ContinuousWrites):
    """Starts continuous write operations and clears writes at the end of the test."""
    c_writes.start()
    yield
    c_writes.clear()
    logger.info("\n\n\n\nThe writes have been cleared.\n\n\n\n")


@pytest.fixture()
def restart_delay(juju: jubilant.Juju, controller_app: str):
    status = juju.status()
    for unit in status.apps[APP_NAME].units | status.apps[controller_app].units:
        patch_restart_delay(juju=juju, unit_name=unit, delay=RESTART_DELAY)
    yield
    status = juju.status()
    for unit in status.apps[APP_NAME].units | status.apps[controller_app].units:
        remove_restart_delay(juju=juju, unit_name=unit)


@pytest.fixture()
def restore_state(juju: jubilant.Juju, kafka_apps):
    """Resets all machines network and Apache Kafka service to the default state."""
    logger.info("Resetting units state")
    restore_funcs = (network_release, network_restore, reset_kafka_service)
    machines = juju.status().machines.values()
    for machine, _func in product(machines, restore_funcs):
        try:
            _func(machine.hostname)
            time.sleep(10)
        except subprocess.CalledProcessError:
            continue

    assert_all_brokers_up(juju)
