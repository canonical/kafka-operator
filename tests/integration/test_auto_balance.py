import logging
import time

import jubilant
import pytest

from integration.ha.continuous_writes import ContinuousWrites
from integration.helpers import (
    APP_NAME,
    DUMMY_NAME,
    REL_NAME_ADMIN,
)
from integration.helpers.ha import (
    assert_continuous_writes_consistency,
)
from integration.helpers.jubilant import (
    all_active_idle,
    check_log_dirs,
    deploy_cluster,
)

logger = logging.getLogger(__name__)


def _assert_partitions_rebalanced(model: str, num_brokers: int, timeout: int = 1200):
    """Assert that all active broker/storages are utilized and have partitions."""
    _wait = 60
    for _ in range(timeout // _wait):
        time.sleep(_wait)
        empty_storages = []
        log_dirs_state = check_log_dirs(model)
        for k, partitions in log_dirs_state.items():
            if not partitions:
                empty_storages.append(k)

        if len(log_dirs_state) != num_brokers:
            logger.info(f"Waiting for exactly {num_brokers} broker/storages...")
            continue

        if len(log_dirs_state) == num_brokers and not empty_storages:
            # all storages have partitions, successful!
            break

        logger.info(f"Following broker/storages are still empty: {','.join(empty_storages)}")


@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
def test_build_and_deploy(
    juju: jubilant.Juju,
    kafka_charm,
    app_charm,
    kraft_mode,
    kafka_apps,
):
    deploy_cluster(
        juju=juju,
        charm=kafka_charm,
        kraft_mode=kraft_mode,
        num_broker=3,
        num_controller=1,
    )
    juju.deploy(app_charm, app=DUMMY_NAME, num_units=1)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=3600,
    )

    juju.integrate(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=20,
        timeout=1200,
    )

    status = juju.status()
    assert status.apps[APP_NAME].app_status.current == "active"
    assert status.apps[DUMMY_NAME].app_status.current == "active"


def test_scale_out(juju: jubilant.Juju, controller_app, kafka_apps, kraft_mode):
    assert juju.model

    c_writes = ContinuousWrites(model=juju.model, app=DUMMY_NAME)
    c_writes.start()

    logger.info("Waiting a minute for continuous writes...")
    time.sleep(60)

    juju.add_unit(APP_NAME, num_units=2)
    time.sleep(30)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=3,
        successes=20,
        timeout=3600,
    )

    _assert_partitions_rebalanced(model=juju.model, num_brokers=5)

    result = c_writes.stop()
    assert_continuous_writes_consistency(result)


def test_scale_in(juju: jubilant.Juju, controller_app, kafka_apps, kraft_mode):
    assert juju.model

    c_writes = ContinuousWrites(model=juju.model, app=DUMMY_NAME)
    c_writes.start()

    logger.info("Waiting a minute for continuous writes...")
    time.sleep(60)

    juju.remove_unit(f"{APP_NAME}/3")
    time.sleep(30)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=3,
        successes=20,
        timeout=3600,
    )

    _assert_partitions_rebalanced(model=juju.model, num_brokers=4)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps),
        delay=3,
        successes=20,
        timeout=3600,
    )

    result = c_writes.stop()
    assert_continuous_writes_consistency(result)
