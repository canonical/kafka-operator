#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import subprocess
import zipfile
from pathlib import Path

import jubilant
import pytest
import tomlkit
from single_kernel_kafka.core.literals import TLS_RELATION

from integration.k8s.helpers import (
    APP_NAME,
    CONTROLLER_NAME,
    DUMMY_NAME,
    KAFKA_CONTAINER,
    REL_NAME_ADMIN,
    TLS_NAME,
    KRaftMode,
)
from integration.k8s.helpers.jubilant import all_active_idle, check_logs, deploy_cluster

logger = logging.getLogger(__name__)

CHANNEL = "4/stable"
CHARMCRAFT = os.environ.get("CHARMCRAFT_BIN", "charmcraft")


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

    # this is equivalent to charmcraft pack, which uses the updated refresh_versions.toml file.
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
def test_in_place_refresh(juju: jubilant.Juju, kraft_mode: KRaftMode):
    """Tests happy path refresh with TLS in KRaft mode."""
    kafka_apps = [APP_NAME] if kraft_mode == "single" else [APP_NAME, CONTROLLER_NAME]
    tls_config = {"ca-common-name": "kafka"}

    deploy_cluster(
        juju=juju,
        charm="kafka-k8s",
        kraft_mode=kraft_mode,
        num_broker=1,
        num_controller=1,
        channel=CHANNEL,
    )

    juju.deploy(TLS_NAME, channel="1/stable", config=tls_config, trust=True)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, TLS_NAME),
        delay=3,
        successes=10,
        timeout=1800,
    )

    if kraft_mode == "multi":
        juju.integrate(f"{CONTROLLER_NAME}:{TLS_RELATION}", TLS_NAME)
    juju.integrate(f"{APP_NAME}:{TLS_RELATION}", TLS_NAME)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, TLS_NAME),
        delay=3,
        successes=10,
        timeout=1800,
    )

    juju.add_unit(APP_NAME, num_units=2)
    juju.wait(
        lambda status: all_active_idle(status, APP_NAME) and len(status.apps[APP_NAME].units) == 3,
        delay=3,
        successes=10,
        timeout=1800,
    )

    leader_unit = None
    for unit_name, unit in juju.status().apps[APP_NAME].units.items():
        if unit.leader:
            leader_unit = unit_name
            break
    assert leader_unit

    logger.info("Calling pre-refresh-check...")
    juju.run(leader_unit, "pre-refresh-check")
    juju.wait(
        lambda status: all_active_idle(status, APP_NAME),
        delay=3,
        successes=10,
        timeout=1000,
    )

    logger.info("Upgrading Kafka...")
    refresh_charm = os.environ.get("REFRESH_CHARM")
    juju.refresh(
        APP_NAME,
        path=refresh_charm,
        resources={"kafka-image": KAFKA_CONTAINER},
    )

    juju.wait(
        lambda status: jubilant.all_agents_idle(status, APP_NAME),
        delay=3,
        successes=10,
        timeout=1000,
    )

    juju.run(leader_unit, "resume-refresh")
    juju.wait(
        lambda status: all_active_idle(status, APP_NAME),
        delay=3,
        successes=10,
        timeout=1000,
    )

    # cleanup existing 'current' Kafka, and remove TLS for next test
    juju.remove_application(APP_NAME, destroy_storage=True, force=True)
    juju.remove_application(TLS_NAME, destroy_storage=True, force=True)
    if kraft_mode == "multi":
        juju.remove_application(CONTROLLER_NAME, destroy_storage=True, force=True)

    # Wait for model to be empty
    juju.wait(
        lambda status: len(status.apps) == 0,
        delay=3,
        successes=5,
        timeout=600,
    )


@pytest.mark.skip(reason="Test controller node instead")
def test_in_place_refresh_consistency(
    juju: jubilant.Juju, kafka_charm, app_charm, kraft_mode: KRaftMode
):
    """Tests non-TLS refresh data consistency during refresh in KRaft mode."""
    kafka_apps = [APP_NAME] if kraft_mode == "single" else [APP_NAME, CONTROLLER_NAME]

    deploy_cluster(
        juju=juju,
        charm=kafka_charm,
        kraft_mode=kraft_mode,
        num_broker=1,
        num_controller=1,
    )

    juju.deploy(app_charm, app=DUMMY_NAME, trust=True)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=1800,
    )

    juju.integrate(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=1800,
    )

    juju.add_unit(APP_NAME, num_units=2)
    juju.wait(
        lambda status: all_active_idle(status, APP_NAME) and len(status.apps[APP_NAME].units) == 3,
        delay=3,
        successes=10,
        timeout=600,
    )

    logger.info("Producing messages before upgrading...")
    juju.run(f"{DUMMY_NAME}/0", "produce")
    juju.wait(
        lambda status: all_active_idle(status, APP_NAME, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=1000,
    )

    check_logs(
        juju=juju,
        kafka_unit_name=f"{APP_NAME}/0",
        topic="test-topic",
    )

    leader_unit = None
    for unit_name, unit in juju.status().apps[APP_NAME].units.items():
        if unit.leader:
            leader_unit = unit_name
            break
    assert leader_unit

    logger.info("Calling pre-refresh-check...")
    juju.run(leader_unit, "pre-refresh-check")
    juju.wait(
        lambda status: all_active_idle(status, APP_NAME, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=1000,
    )

    logger.info("Upgrading Kafka...")
    juju.refresh(
        APP_NAME,
        path=kafka_charm,
        resources={"kafka-image": KAFKA_CONTAINER},
    )

    juju.wait(
        lambda status: jubilant.all_agents_idle(status, APP_NAME, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=1000,
    )

    juju.run(leader_unit, "resume-refresh")
    juju.wait(
        lambda status: all_active_idle(status, APP_NAME, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=1000,
    )

    logger.info("Checking that produced messages can be consumed afterwards...")
    juju.run(f"{DUMMY_NAME}/0", "consume")
    juju.wait(
        lambda status: all_active_idle(status, APP_NAME, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=1000,
    )
