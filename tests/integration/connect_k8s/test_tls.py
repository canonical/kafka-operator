import logging

import pytest
from jubilant_adapters import JujuFixture, gather
from requests.exceptions import ConnectionError, SSLError

from integration.connect_k8s.helpers import (
    APP_NAME,
    CONFIG_DIR,
    IMAGE_RESOURCE_KEY,
    IMAGE_URI,
    KAFKA_APP,
    KAFKA_CHANNEL,
    extract_sans,
    get_certificate,
    make_connect_api_request,
    run_command_on_unit,
    self_signed_ca,
    sign_manual_certs,
)

logger = logging.getLogger(__name__)

TLS_APP = "self-signed-certificates"
TLS_CHANNEL = "1/stable"
TLS_CONFIG = {"ca-common-name": "kafka"}
MANUAL_TLS_NAME = "manual-tls-certificates"
MANUAL_TLS_CHANNEL = "1/stable"


def test_deploy_tls(juju: JujuFixture, kafka_connect_charm):

    gather(
        juju.ext.model.deploy(TLS_APP, channel=TLS_CHANNEL, config=TLS_CONFIG),
        juju.ext.model.deploy(
            kafka_connect_charm,
            application_name=APP_NAME,
            resources={IMAGE_RESOURCE_KEY: IMAGE_URI},
        ),
        juju.ext.model.deploy(
            KAFKA_APP,
            channel=KAFKA_CHANNEL,
            application_name=KAFKA_APP,
            num_units=1,
            config={"roles": "broker,controller"},
        ),
    )

    juju.ext.model.add_relation(APP_NAME, KAFKA_APP)

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, KAFKA_APP, TLS_APP], idle_period=60, timeout=1200, status="active"
        )


def test_enable_tls_on_rest_api(juju: JujuFixture):
    """Checks enabling TLS makes REST interface connections secure."""
    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.add_relation(TLS_APP, APP_NAME)
        juju.ext.model.wait_for_idle(apps=[APP_NAME], idle_period=30, timeout=600, status="active")

    with pytest.raises(ConnectionError):
        _ = make_connect_api_request(juju, proto="http")

    with self_signed_ca(juju, TLS_APP) as ca_file:
        response = make_connect_api_request(juju, proto="https", verify=ca_file.name)
        assert response.status_code == 200

    cert = get_certificate(juju)

    assert TLS_CONFIG["ca-common-name"] in cert.issuer.rfc4514_string()
    assert f"{APP_NAME}-0" in extract_sans(cert)


def test_tls_scale_out(juju: JujuFixture):
    """Checks connect workers scaling functionality with TLS relation."""
    juju.ext.model.applications[APP_NAME].add_units(count=2)
    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME], idle_period=30, timeout=600, status="active", wait_for_exact_units=3
        )

    with self_signed_ca(juju, TLS_APP) as ca_file:
        for unit in juju.ext.model.applications[APP_NAME].units:
            response = make_connect_api_request(
                juju, unit=unit, proto="https", verify=ca_file.name
            )
            assert response.status_code == 200


def test_tls_broken(juju: JujuFixture):
    """Checks broken TLS relation leads to fallback to HTTP on the REST interface."""
    juju.juju("remove-relation", APP_NAME, TLS_APP)

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, KAFKA_APP, TLS_APP], idle_period=60, timeout=1200
        )

    for unit in juju.ext.model.applications[APP_NAME].units:
        with pytest.raises(SSLError):
            _ = make_connect_api_request(juju, unit=unit, proto="https")

        response = make_connect_api_request(juju, unit=unit, proto="http")

        assert response.status_code == 200

        res = run_command_on_unit(juju, unit, f"ls {CONFIG_DIR}")
        file_extensions = {f.split(".")[-1] for f in res.stdout.split() if f}
        print(file_extensions)
        assert not {"pem", "key", "p12", "jks"} & file_extensions


def test_manual_tls_with_no_chain(juju: JujuFixture, tmp_path):
    juju.ext.model.deploy(MANUAL_TLS_NAME, channel=MANUAL_TLS_CHANNEL)

    juju.ext.model.add_relation(APP_NAME, MANUAL_TLS_NAME)

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, MANUAL_TLS_NAME],
            idle_period=30,
            timeout=1000,
            raise_on_error=False,
        )

    ca_file = sign_manual_certs(tmp_path, juju.model)

    juju.ext.model.wait_for_idle(
        apps=[APP_NAME, MANUAL_TLS_NAME],
        idle_period=30,
        timeout=1000,
        raise_on_error=False,
        status="active",
    )

    for unit in juju.ext.model.applications[APP_NAME].units:
        response = make_connect_api_request(juju, unit=unit, proto="https", verify=ca_file)
        assert response.status_code == 200
