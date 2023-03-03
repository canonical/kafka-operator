# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import subprocess

import pytest
from helpers import APP_NAME
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, kafka_charm):
    await asyncio.gather(
        ops_test.model.deploy(kafka_charm, application_name=APP_NAME, num_units=1, series="jammy"),
    )
    # Do not wait for idle, otherwise:
    # FAILED: kafka/0 [executing] waiting: waiting for zookeeper relation
    # await ops_test.model.wait_for_idle()

    cmd = "sh tests/integration/test_observability_integrations.sh".split(" ")
    try:
        result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        for line in e.output.decode("utf-8").strip().split("\n"):
            logger.info(line)
        assert 0, "Test failed"
    else:
        for line in result.stdout.decode("utf-8").strip().split("\n"):
            logger.info(line)

    await ops_test.model.wait_for_idle()
