#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.


import json
import os
import random
import string
from typing import cast

import pytest
from jubilant_adapters import JujuFixture, temp_model_fixture

from integration.connect_machine.helpers import DatabaseFixtureParams


def pytest_addoption(parser):
    """Defines pytest parsers."""
    parser.addoption("--kafka", action="store", help="Kafka version", default="3")


@pytest.fixture(scope="module")
def kafka_version(request: pytest.FixtureRequest) -> int:
    """Returns the Kafka version used for tests`."""
    val = f'{request.config.getoption("--kafka")}' or "3"
    if val not in ("3", "4"):
        raise Exception("Unknown Kafka version, valid options are 3 and 4")

    return int(val)


@pytest.fixture(scope="module")
def juju(request: pytest.FixtureRequest):
    """Pytest fixture that wraps :meth:`jubilant.with_model`.

    This adds command line parameter ``--keep-models`` (see help for details).
    """
    model = request.config.getoption("--model")
    keep_models = bool(request.config.getoption("--keep-models"))

    if model:
        juju = JujuFixture(model=model)
        yield juju
    else:
        with temp_model_fixture(keep=keep_models) as juju:
            yield juju


@pytest.fixture(scope="module", autouse=True)
def switch_model(juju: JujuFixture):
    if not juju.model:
        return

    juju.cli("switch", juju.model, include_model=False)


@pytest.fixture(scope="module")
def kafka_connect_charm(juju: JujuFixture):
    """Build the application charm."""
    charm_path = "connect_machine"
    charm = juju.ext.build_charm(charm_path, use_cache=bool(os.environ.get("CI")))
    return charm


@pytest.fixture(scope="module")
def source_integrator_charm(juju: JujuFixture):
    """Build the source (MySQL) integrator charm."""
    charm_path = "./tests/integration/connect_machine/source-integrator-charm"
    charm = juju.ext.build_charm(charm_path, use_cache=bool(os.environ.get("CI")))
    return charm


@pytest.fixture(scope="module")
def sink_integrator_charm(juju: JujuFixture):
    """Build the sink (PostgreSQL) integrator charm."""
    charm_path = "./tests/integration/connect_machine/sink-integrator-charm"
    charm = juju.ext.build_charm(charm_path, use_cache=bool(os.environ.get("CI")))
    return charm


@pytest.fixture(scope="function")
def mysql_test_data(juju: JujuFixture, request: pytest.FixtureRequest):
    """Loads a MySQL database with test data using the client shipped with MySQL charm.

    Tables are named table_{i}, i starting from 1 to param.no_tables.
    """
    params = cast(DatabaseFixtureParams, request.param)

    mysql_leader = juju.ext.model.applications[params.app_name].units[0]
    get_pass_action = mysql_leader.run_action("get-password", mode="full", dryrun=False)
    response = get_pass_action.wait()

    mysql_root_pass = response.results.get("password")

    def exec_query(query: str):
        query = query.replace("\n", " ")
        cmd = f'mysql -h 127.0.0.1 -u root -p{mysql_root_pass} -e "{query}"'
        # print a truncated output
        print(cmd.replace(mysql_root_pass, "******")[:1000])
        return_code, _, _ = juju.juju("ssh", f"{mysql_leader.name}", cmd)
        assert return_code == 0

    for i in range(1, params.no_tables + 1):

        exec_query(f"""CREATE TABLE {params.db_name}.table_{i} (
            id int NOT NULL AUTO_INCREMENT,
            name varchar(50) DEFAULT NULL,
            price float DEFAULT NULL,
            created_at timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY product_id_uindex (id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci""")

        values = []
        for _ in range(params.no_records):
            random_name = "".join([random.choice(string.ascii_letters) for _ in range(8)])
            random_price = float(random.randint(10, 1000))
            values.append(f"('{random_name}', {random_price})")

        exec_query(
            f"INSERT INTO {params.db_name}.table_{i} (name, price) Values {', '.join(values)}"
        )


@pytest.fixture(scope="module")
def model_uuid(juju: JujuFixture) -> str:
    ret, models_raw, _ = juju.juju("models", "--format", "json")
    assert not ret
    return next(
        iter(
            mdl["model-uuid"]
            for mdl in json.loads(models_raw)["models"]
            if mdl["short-name"] == juju.model
        )
    )
