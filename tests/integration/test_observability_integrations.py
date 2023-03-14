# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import os
import subprocess

import pytest
from pytest_operator.plugin import OpsTest

from .helpers import APP_NAME

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

    # TODO: parametrize the model name "cos"
    await ops_test.model.consume(
        "admin/cos.prometheus",
        application_alias="prometheus",
        controller_name=os.environ["K8S_CONTROLLER"],
    )
    # TODO:
    #  - Enable metallb as part of CI
    #  - Relate prom to traefik

    await asyncio.gather(
        ops_test.model.deploy(
            "ch:grafana-agent-operator", application_name="agent", num_units=1, series="jammy"
        ),
    )
    await ops_test.model.add_relation("agent", "prometheus")
    await ops_test.model.add_relation(f"{APP_NAME}:cos-agent", "agent")
    await ops_test.model.wait_for_idle()

    # TODO: Assert that kafka metrics appear in prometheus
