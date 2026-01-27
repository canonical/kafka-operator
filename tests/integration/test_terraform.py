#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Simple Terraform smoke tests."""

import json
import logging
import os

import pytest
from jubilant import Juju

from integration.helpers.jubilant import APP_NAME, all_active_idle

logger = logging.getLogger(__name__)


TFVARS_DEFAULTS = {
    "app_name": APP_NAME,
    "config": {"roles": "broker,controller"},
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


@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
def test_deployment_active(juju: Juju, model_uuid: str, tmp_path):
    """Test that Kafka is deployed and active."""
    working_dir = _deploy_terraform(tmp_path, tfvars={"model_uuid": model_uuid})

    juju.wait(
        lambda status: all_active_idle(status, APP_NAME),
        delay=3,
        successes=20,
        timeout=900,
    )

    _destroy_terraform(working_dir)

    juju.wait(
        lambda status: len(status.apps) == 0,
        delay=3,
        successes=20,
        timeout=900,
    )


@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
def test_deployment_on_machines(juju: Juju, model_uuid: str, tmp_path):
    """Test that `machines` TF variable work as expected."""
    # Add machines and wait for them to start
    juju.cli("add-machine", "-n", "2")
    juju.wait(
        lambda status: all(
            machine_status.juju_status.current == "started"
            for machine_status in status.machines.values()
        ),
        delay=3,
        successes=10,
        timeout=600,
    )

    machines = list(juju.status().machines)
    working_dir = _deploy_terraform(
        tmp_path, tfvars={"model_uuid": model_uuid, "machines": machines}
    )

    juju.wait(
        lambda status: all_active_idle(status, APP_NAME),
        delay=3,
        successes=20,
        timeout=900,
    )

    assert len(juju.status().apps[APP_NAME].units) == 2

    _destroy_terraform(working_dir)

    juju.wait(
        lambda status: len(status.apps) == 0,
        delay=3,
        successes=20,
        timeout=900,
    )
