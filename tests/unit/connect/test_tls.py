import dataclasses
import json
import logging
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from charms.tls_certificates_interface.v3.tls_certificates import (
    CertificateAvailableEvent,
    CertificateExpiringEvent,
    generate_ca,
    generate_certificate,
    generate_csr,
    generate_private_key,
)
from ops.testing import Context, PeerRelation, Relation, State
from single_kernel_kafka.core.connect_models import TLSContext
from single_kernel_kafka.core.literals import ConnectStatus as Status
from single_kernel_kafka.managers.tls import TLSManager

from .helpers import PEER_REL, TLS_REL, ConnectCharm

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class TLSArtifacts:
    ca_key: bytes
    ca: bytes
    private_key: bytes
    cert: bytes
    csr: bytes


@pytest.fixture()
def tls_artifacts() -> TLSArtifacts:
    ca_key = generate_private_key()
    ca = generate_ca(private_key=ca_key, subject="TEST-CA")
    private_key = generate_private_key()
    csr = generate_csr(private_key=private_key, subject="kafka-connect/0")
    cert = generate_certificate(csr, ca, ca_key)
    return TLSArtifacts(ca_key=ca_key, ca=ca, private_key=private_key, cert=cert, csr=csr)


@pytest.mark.parametrize("is_leader", [True, False])
def test_tls_relation_created(ctx: Context, base_state: State, is_leader: bool) -> None:
    """Checks TLS `relation-created` enables `tls` on peer app data interface."""
    # Given
    state_in = base_state
    peer_rel = PeerRelation(PEER_REL, PEER_REL)
    tls_rel = Relation(TLS_REL, TLS_REL)

    state_in = dataclasses.replace(base_state, relations=[tls_rel, peer_rel], leader=is_leader)

    # When
    state_out = ctx.run(ctx.on.relation_created(tls_rel), state_in)
    peer_rel_out = state_out.get_relation(peer_rel.id)

    # Then
    assert state_out.unit_status == Status.MISSING_KAFKA.value.status
    if is_leader:
        assert peer_rel_out.local_app_data.get("tls") == "enabled"
    else:
        assert not peer_rel_out.local_app_data.get("tls")


@pytest.mark.parametrize("is_leader", [True, False])
def test_tls_relation_broken(ctx: Context, base_state: State, is_leader: bool) -> None:
    """Checks TLS `relation-broken` disables `tls` on peer app data interface and triggers proper cleanup."""
    # Given
    state_in = base_state
    peer_rel = PeerRelation(
        PEER_REL,
        PEER_REL,
        local_app_data={"tls": "enabled"},
        local_unit_data={
            TLSContext.CA: "ca",
            TLSContext.PRIVATE_KEY: "private-key",
            TLSContext.CERT: "cert",
        },
    )
    tls_rel = Relation(TLS_REL, TLS_REL)

    state_in = dataclasses.replace(base_state, relations=[tls_rel, peer_rel], leader=is_leader)

    # When
    state_out = ctx.run(ctx.on.relation_broken(tls_rel), state_in)
    peer_rel_out = state_out.get_relation(peer_rel.id)

    # Then
    assert state_out.unit_status == Status.MISSING_KAFKA.value.status
    for key in TLSContext.KEYS:
        assert not peer_rel_out.local_unit_data.get(key)

    if is_leader:
        assert not peer_rel_out.local_app_data.get("tls")
    else:
        assert peer_rel_out.local_app_data.get("tls") == "enabled"


@pytest.mark.parametrize("is_leader", [True, False])
@pytest.mark.parametrize(
    "tls_init_data",
    [
        {},
        {
            TLSContext.PRIVATE_KEY: generate_private_key().decode("utf-8"),
            TLSContext.KEYSTORE_PASSWORD: "password",
            TLSContext.TRUSTSTORE_PASSWORD: "password",
        },
    ],
)
def test_tls_relation_joined(
    ctx: Context, base_state: State, is_leader: bool, tls_init_data: dict
) -> None:
    """Checks TLS `relation-joined` triggers appropriate setup of private key, keystore and truststore on the unit."""
    # Given
    state_in = base_state
    peer_rel = PeerRelation(
        PEER_REL,
        PEER_REL,
        local_app_data={"tls": "enabled"},
    )
    tls_rel = Relation(TLS_REL, TLS_REL)

    state_in = dataclasses.replace(base_state, relations=[tls_rel, peer_rel], leader=is_leader)

    # When
    with ctx(ctx.on.relation_joined(tls_rel), state_in) as mgr:
        charm: ConnectCharm = cast(ConnectCharm, mgr.charm)
        if tls_init_data:
            charm.context.worker_unit.update(tls_init_data)
        state_out = mgr.run()

        assert mgr.charm.workload.write.call_count == 1
        assert mgr.charm.workload.write.call_args_list[0][0][0].startswith("truststore=")

    secret_contents = {
        k: v for secret in state_out.secrets for k, v in secret.latest_content.items()
    }

    # Then
    assert len(secret_contents) > 0
    assert state_out.unit_status == Status.MISSING_KAFKA.value.status
    assert secret_contents.get(TLSContext.PRIVATE_KEY, "")
    assert secret_contents.get(TLSContext.CSR, "")
    assert secret_contents.get(TLSContext.KEYSTORE_PASSWORD, "")
    assert secret_contents.get(TLSContext.TRUSTSTORE_PASSWORD, "")

    if tls_init_data:
        assert secret_contents.get(TLSContext.KEYSTORE_PASSWORD, "") == "password"
        assert secret_contents.get(TLSContext.TRUSTSTORE_PASSWORD, "") == "password"


@pytest.mark.parametrize("chain", [[], ["cert-1", "cert-2", "cert-3"]])
def test_tls_certificate_available(
    ctx: Context, base_state: State, chain, tls_artifacts: TLSArtifacts, active_service: MagicMock
) -> None:
    """Checks on `certificate-available` event, local unit data is updated accordingly."""
    # Given
    state_in = base_state
    peer_rel = PeerRelation(
        PEER_REL,
        PEER_REL,
        local_app_data={"tls": "enabled"},
        local_unit_data={TLSContext.CSR: tls_artifacts.csr.decode("utf-8")},
    )
    tls_rel = Relation(TLS_REL, TLS_REL)
    tls_manager_mock = MagicMock(spec=TLSManager)
    event = CertificateAvailableEvent(
        handle=MagicMock(),
        certificate=generate_certificate(
            tls_artifacts.csr, tls_artifacts.ca, tls_artifacts.ca_key
        ).decode("utf-8"),
        certificate_signing_request=tls_artifacts.csr.decode("utf-8"),
        ca=tls_artifacts.ca.decode("utf-8"),
        chain=chain,
    )

    state_in = dataclasses.replace(base_state, relations=[tls_rel, peer_rel])

    # When
    with (ctx(ctx.on.update_status(), state_in) as mgr,):
        charm: ConnectCharm = cast(ConnectCharm, mgr.charm)
        charm.tls_manager = tls_manager_mock
        charm.tls_manager.sans_change_detected = False
        charm.tls._on_certificate_available(event)
        state_out = mgr.run()

    # Then
    peer_rel_out = state_out.get_relation(peer_rel.id)

    assert state_out.unit_status == Status.MISSING_KAFKA.value.status
    tls_manager_mock.configure.assert_called_once()
    assert peer_rel_out.local_unit_data.get(TLSContext.CERT, "")
    assert peer_rel_out.local_unit_data.get(TLSContext.CA, "")
    assert peer_rel_out.local_unit_data.get(TLSContext.CHAIN, "")
    assert len(json.loads(peer_rel_out.local_unit_data.get(TLSContext.CHAIN, ""))) == len(chain)


def test_tls_certificate_expiring(
    ctx: Context, base_state: State, tls_artifacts: TLSArtifacts, active_service: MagicMock
) -> None:
    """Checks `certificate-expiring` event leads to new CSR being submitted."""
    # Given
    other_private_key = generate_private_key()
    csr = generate_csr(private_key=other_private_key, subject="kafka-connect/0")

    state_in = base_state
    peer_rel = PeerRelation(
        PEER_REL,
        PEER_REL,
        local_app_data={"tls": "enabled"},
    )
    tls_rel = Relation(TLS_REL, TLS_REL)
    event = CertificateExpiringEvent(
        handle=MagicMock(),
        certificate=tls_artifacts.cert.decode("utf-8"),
        expiry="1990-01-01 00:00:00",
    )

    state_in = dataclasses.replace(base_state, relations=[tls_rel, peer_rel])

    # When
    with (ctx(ctx.on.update_status(), state_in) as mgr,):
        charm: ConnectCharm = cast(ConnectCharm, mgr.charm)
        charm.context.worker_unit.update(
            items={
                TLSContext.CSR: csr.decode("utf-8"),
                TLSContext.PRIVATE_KEY: tls_artifacts.private_key.decode("utf-8"),
            }
        )
        charm.tls._on_certificate_expiring(event)
        state_out = mgr.run()

    secret_contents = {
        k: v for secret in state_out.secrets for k, v in secret.latest_content.items()
    }

    # Then
    # TODO: better assertions?
    assert state_out.unit_status == Status.MISSING_KAFKA.value.status
    assert secret_contents.get(TLSContext.PRIVATE_KEY) == tls_artifacts.private_key.decode("utf-8")
    assert secret_contents.get(TLSContext.CSR) != csr.decode("utf-8")


@pytest.mark.parametrize("sans_changed", [False, True])
def test_sans_change_leads_to_new_cert_request(
    ctx: Context,
    base_state: State,
    tls_artifacts: TLSArtifacts,
    sans_changed: bool,
    active_service: MagicMock,
) -> None:
    """Checks whether a SANs change leads to the old certificate being removed and new certificate requested."""
    # Given
    state_in = base_state
    peer_rel = PeerRelation(
        PEER_REL,
        PEER_REL,
        local_app_data={"tls": "enabled"},
        local_unit_data={
            TLSContext.CERT: tls_artifacts.cert.decode("utf-8"),
            TLSContext.CA: tls_artifacts.ca.decode("utf-8"),
            TLSContext.PRIVATE_KEY: tls_artifacts.private_key.decode("utf-8"),
            TLSContext.CSR: "old-csr",
            "private-address": "10.10.10.10",
        },
    )
    tls_rel = Relation(TLS_REL, TLS_REL)
    state_in = dataclasses.replace(base_state, relations=[tls_rel, peer_rel])

    with patch(
        "single_kernel_kafka.managers.tls.TLSManager.sans_changed", return_value=sans_changed
    ):
        state_out = ctx.run(ctx.on.config_changed(), state_in)

    peer_rel_out = state_out.get_relation(peer_rel.id)

    if sans_changed:
        assert peer_rel_out.local_unit_data.get(TLSContext.CSR, "")
        assert peer_rel_out.local_unit_data.get(TLSContext.CSR, "") != "old-csr"
        # cert is probably empty at this point, but we just care that old cert is not used anymore
        assert peer_rel_out.local_unit_data.get(TLSContext.CERT, "") != tls_artifacts.cert.decode(
            "utf-8"
        )
    else:
        assert peer_rel_out.local_unit_data.get(TLSContext.CSR, "") == "old-csr"
        assert peer_rel_out.local_unit_data.get(TLSContext.CERT, "") == tls_artifacts.cert.decode(
            "utf-8"
        )
