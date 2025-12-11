import logging

import jubilant
import pytest

from integration.ha.continuous_writes import ContinuousWrites
from integration.helpers import (
    APP_NAME,
    CONTROLLER_NAME,
    DUMMY_NAME,
    REL_NAME_ADMIN,
    TLS_CHANNEL,
    TLS_NAME,
    sign_manual_certs,
)
from integration.helpers.ha import (
    assert_all_brokers_up,
    assert_all_controllers_up,
    assert_continuous_writes_consistency,
    assert_quorum_healthy,
)
from integration.helpers.jubilant import (
    BASE,
    all_active_idle,
    deploy_cluster,
)
from literals import INTERNAL_TLS_RELATION, SECURITY_PROTOCOL_PORTS, TLS_RELATION

logger = logging.getLogger(__name__)


MANUAL_TLS_NAME = "manual-tls-certificates"
MANUAL_TLS_CHANNEL = "1/stable"

TLS_APP_CLIENT = "ca"
TLS_APP_BROKER = "ca-two"
TLS_APP_CONTROLLER = "ca-three"


@pytest.fixture
def tls_apps(kraft_mode):
    apps = [TLS_APP_CLIENT, TLS_APP_BROKER]
    return apps if kraft_mode == "single" else apps + [TLS_APP_CONTROLLER]


@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
def test_build_and_deploy(
    juju: jubilant.Juju, kafka_charm, app_charm, kraft_mode, kafka_apps, tls_apps
):
    deploy_cluster(
        juju=juju,
        charm=kafka_charm,
        kraft_mode=kraft_mode,
        num_broker=3,
        num_controller=3,
    )
    juju.deploy(app_charm, app=DUMMY_NAME, num_units=1, base=BASE)
    juju.deploy(TLS_NAME, app=TLS_APP_CLIENT, to="0", channel=TLS_CHANNEL)
    juju.deploy(MANUAL_TLS_NAME, app=TLS_APP_BROKER, to="1", channel=MANUAL_TLS_CHANNEL)
    juju.deploy(TLS_NAME, app=TLS_APP_CONTROLLER, to="2")

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, *tls_apps, DUMMY_NAME),
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


def test_integrate_client_tls(juju: jubilant.Juju, kafka_apps, tls_apps):
    juju.integrate(f"{APP_NAME}:{TLS_RELATION}", TLS_APP_CLIENT)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, *tls_apps),
        delay=3,
        successes=10,
        timeout=3600,
    )

    assert_all_brokers_up(juju, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client)


def test_integrate_internal_tls(
    juju: jubilant.Juju, controller_app, kafka_apps, tls_apps, kraft_mode
):
    assert juju.model  # this is to silent the linter
    c_writes = ContinuousWrites(model=juju.model, app=DUMMY_NAME, produce_rate=5)
    c_writes.start()

    juju.integrate(f"{APP_NAME}:{INTERNAL_TLS_RELATION}", TLS_APP_BROKER)
    if kraft_mode == "multi":
        juju.integrate(f"{CONTROLLER_NAME}:{INTERNAL_TLS_RELATION}", TLS_APP_CONTROLLER)

    juju.wait(
        lambda status: "3 outstanding requests" in status.apps[TLS_APP_BROKER].app_status.message,
        timeout=900,
    )

    sign_manual_certs(juju.model, manual_app=TLS_APP_BROKER)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, *tls_apps),
        delay=3,
        successes=20,
        timeout=3600,
    )

    result = c_writes.stop()

    assert_all_brokers_up(juju, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client)
    assert_all_controllers_up(juju, controller_app=controller_app)
    assert_continuous_writes_consistency(result)
    assert_quorum_healthy(juju, kraft_mode=kraft_mode)
