#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import secrets
import subprocess
from typing import Generator

import jubilant
import pytest

from integration.helpers import APP_NAME, REL_NAME_ADMIN
from integration.helpers.jubilant import (
    BASE,
    all_active_idle,
    deploy_cluster,
    get_provider_data,
    get_relation_data,
)
from literals import PEER

logger = logging.getLogger(__name__)


TEST_APP = "app"
DEFAULT_NETWORK_CIDR = "10.0.0.0/8"
DEFAULT_SPACE = "alpha"
DEFAULT_NETWORK_NAME = "lxdbr0"
OTHER_NETWORK_CIDR = "172.30.0.1/24"
OTHER_SPACE = "test"
LXD_NETWORK_OPTIONS = [
    "ipv4.nat=true",
    "ipv6.address=none",
    "dns.mode=none",
]


@pytest.fixture(scope="module")
def other_network() -> Generator[str, None, None]:
    """Creates and/or returns a LXD network with `OTHER_NETWORK_CIDR` range of IPv4 addresses."""
    # We should set `dns.mode=none` for all LXD networks in this scenario.
    # This is required to avoid DNS name conflict issues
    # due to the fact that multiple NICs are connected to the same bridge network:
    # https://discuss.linuxcontainers.org/t/error-failed-start-validation-for-device-enp3s0f0-instance-dns-name-net17-nicole-munoz-marketing-already-used-on-network/15586/9?page=2
    subprocess.check_output(
        f"sudo lxc network set {DEFAULT_NETWORK_NAME} dns.mode=none",
        shell=True,
        stderr=subprocess.PIPE,
    )
    raw = subprocess.check_output(
        "sudo lxc network list --format json", shell=True, stderr=subprocess.PIPE
    )
    networks_json = json.loads(raw)
    # Check if a network with the provided CIDR already exists:
    for network in networks_json:
        if network.get("config", {}).get("ipv4.address") == OTHER_NETWORK_CIDR:
            logger.info(
                f'Exisiting network {network["name"]} found with CIDR: {OTHER_NETWORK_CIDR}'
            )
            yield network["name"]
            return

    name = f"net-{secrets.token_hex(4)}"

    subprocess.check_output(
        f"sudo lxc network create {name} ipv4.address={OTHER_NETWORK_CIDR} {' '.join(LXD_NETWORK_OPTIONS)}",
        shell=True,
        stderr=subprocess.PIPE,
    )
    yield name

    logger.info(f"Cleaning up {name} network...")
    try:
        subprocess.check_output(
            f"sudo lxc network delete --force-local {name}",
            shell=True,
            stderr=subprocess.PIPE,
        )
    except Exception as e:
        logger.error(f"Network cleanup failed, details: {e}")
        logger.info(f"Try deleting the network manually using `lxc network delete {name}`")


@pytest.mark.abort_on_fail
def test_add_space(juju: jubilant.Juju, other_network: str) -> None:
    """Adds `OTHER_SPACE` juju space."""
    # reload subnets and move `OTHER_NETWORK_CIDR` subnet to the `OTHER_SPACE`
    juju.cli("reload-spaces")
    juju.cli("add-space", OTHER_SPACE, OTHER_NETWORK_CIDR)


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
def test_deploy_active(
    juju: jubilant.Juju, kafka_charm, app_charm, kraft_mode, kafka_apps
) -> None:
    """Deploys a cluster of Kafka with 3 brokers and a test app, waits for `active|idle`."""
    deploy_cluster(
        juju=juju,
        charm=kafka_charm,
        kraft_mode=kraft_mode,
        num_broker=3,
        bind={"kafka-client": OTHER_SPACE},
    )
    juju.deploy(
        app_charm,
        app=TEST_APP,
        num_units=1,
        base=BASE,
        bind={REL_NAME_ADMIN: OTHER_SPACE},
    )

    juju.integrate(APP_NAME, f"{TEST_APP}:{REL_NAME_ADMIN}")

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, TEST_APP),
        delay=3,
        successes=20,
        timeout=1800,
    )


@pytest.mark.abort_on_fail
def test_endpoints_are_set_based_on_network_binds(juju: jubilant.Juju, kafka_apps) -> None:
    assert juju.model
    # We should have set client's IP from the `OTHER_NETWORK`
    provider_data = get_provider_data(
        juju.model, owner=APP_NAME, unit_name=f"{TEST_APP}/0", relation_interface=REL_NAME_ADMIN
    )
    for endpoint in provider_data["endpoints"].split(","):
        assert endpoint.startswith(OTHER_NETWORK_CIDR.split(".")[0])

    # We should have set `ip` (internal peer IP address) from the `DEFAULT_NETWORK`
    for unit in juju.status().apps[APP_NAME].units:
        unit_data = get_relation_data(juju, unit, PEER, key="local-unit")
        ip = unit_data.get("data", {}).get("ip", "")
        logging.info(f"{unit}: {ip}")
        assert ip.startswith(DEFAULT_NETWORK_CIDR.split(".")[0])

    # now bind kafka to the new space
    juju.cli("bind", APP_NAME, OTHER_SPACE)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, TEST_APP),
        delay=3,
        successes=20,
        timeout=1800,
    )

    # Now we should set `ip` from the `OTHER_NETWORK`
    for unit in juju.status().apps[APP_NAME].units:
        unit_data = get_relation_data(juju, unit, PEER, key="local-unit")
        ip = unit_data.get("data", {}).get("ip", "")
        logging.info(f"{unit}: {ip}")
        assert ip.startswith(OTHER_NETWORK_CIDR.split(".")[0])
