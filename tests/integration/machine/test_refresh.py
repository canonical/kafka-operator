#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import subprocess
import time
import zipfile
from pathlib import Path

import jubilant
import pytest
import tomlkit

from integration.machine.helpers import (
    APP_NAME,
    DUMMY_NAME,
    REL_NAME_ADMIN,
)
from integration.machine.helpers.jubilant import (
    BASE,
    all_active_idle,
    check_logs,
    deploy_cluster,
    produce_and_check_logs,
)

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker
CHANNEL = "4/stable"


def test_repack_charm(
    tmp_path_factory: pytest.TempPathFactory,
    kafka_charm,
):
    """Unpack the built charm and repack using a refresh-able version."""
    base = tmp_path_factory.mktemp("refresh-charm-")
    os.system(f"unzip -q {kafka_charm} -d {base}")

    # get the latest refresh git tag, i.e. v4/1.##.#
    current_tag_cmd_pipeline = [
        "git ls-remote --tags https://github.com/canonical/kafka-operator",
        "grep v4",  # filter v4 tags
        r"sed -n 's_^.*/\([^/}]*\)$_\1_p'",  # only return tag names, e.g. 1.22.0
        r"sed 's/1\.//g'",  # strip the "1." part
        "sort -n",  # numeric sort
        "tail -n 1",  # return the last one
    ]
    current_tag = subprocess.check_output(
        " | ".join(current_tag_cmd_pipeline),
        shell=True,
        stderr=subprocess.PIPE,
    )

    # compute the next refresh version, which will be released to edge.
    # same logic as .github/workflows/release.yaml
    next_ver = int(float(current_tag) + 1)
    refresh_version = f"4/1.{next_ver}.0"

    # rewrite the refresh_versions.toml file using the new computed version.
    with open(f"{base}/refresh_versions.toml") as file:
        versions = tomlkit.load(file)
    versions["charm"] = refresh_version
    with open(f"{base}/refresh_versions.toml", "w") as file:
        tomlkit.dump(versions, file)

    # this is equivalent to charmcraft pack,
    # and uses the updated refresh_versions.toml file.
    # basically, we're using the `base` folder as the prime dir.
    # see: https://github.com/canonical/charmcraft/blob/a2503a34fad32de497b95c19ae355121a54327a8/charmcraft/utils/file.py#L59-L72
    output_file = f"kafka_refresh_{refresh_version.replace('/', '_')}.charm"
    with zipfile.ZipFile(output_file, mode="w", compression=zipfile.ZIP_DEFLATED) as charm_zip:
        for root, _, files in os.walk(base, followlinks=True):
            for file in files:
                file_path = Path(root) / file
                archive_name = file_path.relative_to(base)
                charm_zip.write(file_path, arcname=archive_name)

    os.environ.update({"REFRESH_CHARM": f"./{output_file}"})


@pytest.mark.abort_on_fail
def test_in_place_upgrade(juju: jubilant.Juju, app_charm, kraft_mode, controller_app):
    deploy_cluster(juju=juju, charm="kafka", kraft_mode=kraft_mode, num_broker=3, channel=CHANNEL)
    juju.deploy(app_charm, app=DUMMY_NAME, num_units=1, base=BASE)

    # Get kafka apps list for waiting
    kafka_apps = [APP_NAME] if kraft_mode == "single" else [APP_NAME, controller_app]

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=1800,
    )

    status = juju.status()
    assert status.apps[APP_NAME].app_status.current == "active"
    assert status.apps[controller_app].app_status.current == "active"

    juju.integrate(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=1800,
    )

    logger.info("Producing messages before upgrading")
    produce_and_check_logs(
        juju=juju,
        kafka_unit_name=f"{APP_NAME}/0",
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="hot-topic",
        replication_factor=3,
        num_partitions=1,
    )

    # Find leader unit
    status = juju.status()
    leader_unit = None
    for unit_name, unit in status.apps[APP_NAME].units.items():
        if unit.leader:
            leader_unit = unit_name
            break
    assert leader_unit

    logger.info("Calling pre-refresh-check")
    juju.run(leader_unit, "pre-refresh-check")

    # ensure action completes
    time.sleep(10)

    logger.info("Upgrading Kafka...")
    refresh_charm = os.environ.get("REFRESH_CHARM")
    juju.refresh(APP_NAME, path=str(refresh_charm))
    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=3,
        successes=40,
        timeout=1800,
    )

    logger.info("Check that produced messages can be consumed afterwards")
    check_logs(
        juju=juju,
        kafka_unit_name=f"{APP_NAME}/0",
        topic="hot-topic",
    )


@pytest.mark.abort_on_fail
def test_controller_upgrade_multinode(juju: jubilant.Juju, kraft_mode, controller_app):
    """Test upgrading the controller separately in multi-node mode."""
    if kraft_mode != "multi":
        logger.info(f"Skipping controller upgrade test because we're using {kraft_mode} mode.")
        return

    logger.info("Producing messages before controller upgrade")
    produce_and_check_logs(
        juju=juju,
        kafka_unit_name=f"{APP_NAME}/0",
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="controller-upgrade-topic",
        replication_factor=3,
        num_partitions=1,
    )

    # Find controller leader unit
    status = juju.status()
    controller_leader_unit = None
    for unit_name, unit in status.apps[controller_app].units.items():
        if unit.leader:
            controller_leader_unit = unit_name
            break
    assert controller_leader_unit

    logger.info("Calling pre-refresh-check on controller")
    juju.run(controller_leader_unit, "pre-refresh-check")

    # ensure action completes
    time.sleep(10)

    logger.info("Upgrading Controller...")
    refresh_charm = os.environ.get("REFRESH_CHARM")
    juju.refresh(controller_app, path=str(refresh_charm))
    juju.wait(
        lambda status: all_active_idle(status, controller_app, APP_NAME),
        delay=3,
        successes=40,
        timeout=1800,
    )

    logger.info("Check that produced messages can still be consumed after controller upgrade")
    check_logs(
        juju=juju,
        kafka_unit_name=f"{APP_NAME}/0",
        topic="controller-upgrade-topic",
    )
