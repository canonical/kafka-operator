#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import subprocess
from itertools import product

import pytest
from pytest_operator.plugin import OpsTest

from integration.ha.continuous_writes import ContinuousWrites
from integration.helpers.ha import (
    RESTART_DELAY,
    all_brokers_up,
    network_release,
    network_restore,
    patch_restart_delay,
    remove_restart_delay,
    reset_kafka_service,
)
from integration.helpers.pytest_operator import (
    APP_NAME,
)

logger = logging.getLogger(__name__)


@pytest.fixture()
async def c_writes(ops_test: OpsTest):
    """Creates instance of the ContinuousWrites."""
    app = APP_NAME
    return ContinuousWrites(ops_test, app)


@pytest.fixture()
async def c_writes_runner(ops_test: OpsTest, c_writes: ContinuousWrites):
    """Starts continuous write operations and clears writes at the end of the test."""
    c_writes.start()
    yield
    c_writes.clear()
    logger.info("\n\n\n\nThe writes have been cleared.\n\n\n\n")


@pytest.fixture()
async def restart_delay(ops_test: OpsTest):
    for unit in ops_test.model.applications[APP_NAME].units:
        await patch_restart_delay(ops_test=ops_test, unit_name=unit.name, delay=RESTART_DELAY)
    yield
    for unit in ops_test.model.applications[APP_NAME].units:
        await remove_restart_delay(ops_test=ops_test, unit_name=unit.name)


@pytest.fixture()
async def restore_state(ops_test: OpsTest, kafka_apps):
    """Resets all machines network and Apache Kafka service to the default state."""
    logger.info("Resetting units state")
    restore_funcs = (network_release, network_restore, reset_kafka_service)
    machines = ops_test.model.machines.values()
    for machine, _func in product(machines, restore_funcs):
        try:
            _func(machine.hostname)
            await asyncio.sleep(10)
        except subprocess.CalledProcessError:
            continue

    await all_brokers_up(ops_test)
