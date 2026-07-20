#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Simple Terraform smoke tests."""

import json
import logging
import os
import random

from helpers import APP_NAME
from jubilant_adapters import JujuFixture
from single_kernel_kafka.core.literals import ConnectStatus as Status

logger = logging.getLogger(__name__)


TFVARS_DEFAULTS = {
    "app_name": APP_NAME,
    "units": 3,
}
TFVARS_FILENAME = "test.tfvars.json"


def _deploy_terraform(tmp_path, tfvars: dict = {}) -> str:
    """Deploy the charm Terraform module, using a provided set of variables."""
    tf_path = tmp_path / "terraform"
    tf_path.mkdir()
    logger.info(f"Using {tf_path}")
    os.system(f"cp -R terraform/* {tf_path}/")

    _tfvars = TFVARS_DEFAULTS | tfvars
    with open(f"{tf_path}/{TFVARS_FILENAME}", "w") as f:
        json.dump(_tfvars, f, indent=4)

    ret_code = os.system(f"terraform -chdir={tf_path} init")
    assert not ret_code
    ret_code = os.system(
        f"terraform -chdir={tf_path} apply -var-file={tf_path}/{TFVARS_FILENAME} -auto-approve"
    )
    assert not ret_code

    return tf_path


def _destroy_terraform(working_dir: str) -> None:
    """Destroy the Terraform module and related tmp resources."""
    ret_code = os.system(
        f"terraform -chdir={working_dir} destroy -var-file={working_dir}/{TFVARS_FILENAME} -auto-approve"
    )
    assert not ret_code

    os.system(f"rm -rf {working_dir}")


def test_deployment_active(juju: JujuFixture, model_uuid: str, tmp_path):
    """Test that application is deployed and active."""
    working_dir = _deploy_terraform(tmp_path, tfvars={"model_uuid": model_uuid})

    juju.ext.model.wait_for_idle(apps=[APP_NAME], idle_period=30, timeout=900, status="blocked")
    assert (
        juju.ext.model.applications[APP_NAME].status_message
        == Status.MISSING_KAFKA.value.status.message
    )

    _destroy_terraform(working_dir)

    juju.ext.model.block_until(
        lambda: len(juju.ext.model.units) == 0
        and len(juju.ext.model.machines) == 0
        and len(juju.ext.model.applications) == 0,
        timeout=900,
    )


def test_deployment_on_machines(juju: JujuFixture, model_uuid: str, tmp_path):
    """Test that `machines` TF variable work as expected."""
    # Add machines and wait for them to start
    juju.juju("add-machine", "--base", "ubuntu@22.04", "-n", "3")

    juju.ext.model.block_until(
        lambda: len(juju.ext.model.machines) == 3
        and {machine.agent_status for machine in juju.ext.model.machines.values()} == {"started"},
        timeout=900,
    )

    machines = list(juju.ext.model.machines)
    target_machine = random.choice(machines)

    # Deploy 1 unit on a target machine
    working_dir = _deploy_terraform(
        tmp_path, tfvars={"model_uuid": model_uuid, "machines": [target_machine]}
    )

    juju.ext.model.wait_for_idle(apps=[APP_NAME], idle_period=30, timeout=900, status="blocked")
    assert (
        juju.ext.model.applications[APP_NAME].status_message
        == Status.MISSING_KAFKA.value.status.message
    )

    status = juju.ext.model.applications
    assert len(status[APP_NAME].units) == 1
    deployed_unit = next(iter(status[APP_NAME].units))
    assert deployed_unit.machine.id == target_machine

    _destroy_terraform(working_dir)

    juju.ext.model.block_until(
        lambda: len(juju.ext.model.units) == 0 and len(juju.ext.model.applications) == 0,
        timeout=900,
    )
