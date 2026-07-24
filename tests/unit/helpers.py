#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import yaml
from charmlibs.interfaces.tls_certificates import (
    generate_ca,
    generate_certificate,
    generate_csr,
    generate_private_key,
)

SUBSTRATE = os.environ.get("SUBSTRATE", "vm")
SUBSTRATE_CLS = "Machine" if SUBSTRATE == "vm" else "K8s"
CONFIG = yaml.safe_load(Path(f"./{SUBSTRATE_CLS.lower()}/config.yaml").read_text())
ACTIONS = yaml.safe_load(Path(f"./{SUBSTRATE_CLS.lower()}/actions.yaml").read_text())
METADATA = yaml.safe_load(Path(f"./{SUBSTRATE_CLS.lower()}/metadata.yaml").read_text())

if SUBSTRATE == "vm":
    from machine.src.charm import KafkaCharm
else:
    from k8s.src.charm import KafkaCharm


_charm_cls = KafkaCharm


@dataclass
class TLSArtifacts:
    certificate: str
    private_key: str
    ca: str
    chain: list[str]
    signing_cert: str
    signing_key: str


def generate_tls_artifacts(
    subject: str = "some-app/0",
    sans_dns: list[str] = ["localhost"],
    sans_ip: list[str] = ["127.0.0.1"],
    with_intermediate: bool = False,
) -> TLSArtifacts:
    """Generates necessary TLS artifacts for TLS tests.

    Args:
        subject (str, optional): Certificate Subject Name. Defaults to "some-app/0".
        sans_dns (list[str], optional): List of SANS DNS addresses. Defaults to ["localhost"].
        sans_ip (list[str], optional): List of SANS IP addresses. Defaults to ["127.0.0.1"].
        with_intermediate (bool, optional): Whether or not should use and intermediate CA to sign the end cert. Defaults to False.

    Returns:
        TLSArtifacts: Object containing required TLS Artifacts.
    """
    validity = timedelta(days=365)

    # CA
    ca_key = generate_private_key()
    ca = generate_ca(private_key=ca_key, validity=validity, common_name="some-ca")
    signing_cert, signing_key = ca, ca_key

    # Intermediate?
    if with_intermediate:
        intermediate_key = generate_private_key()
        intermediate_csr = generate_csr(
            private_key=intermediate_key,
            common_name="some-intermediate",
        )
        intermediate_cert = generate_certificate(
            csr=intermediate_csr,
            ca=ca,
            ca_private_key=ca_key,
            validity=validity,
            is_ca=True,
        )
        signing_cert, signing_key = intermediate_cert, intermediate_key

    key = generate_private_key()
    csr = generate_csr(
        private_key=key,
        common_name=subject,
        sans_dns=frozenset(sans_dns),
        sans_ip=frozenset(sans_ip),
    )
    cert = generate_certificate(
        csr=csr, ca=signing_cert, ca_private_key=signing_key, validity=validity
    )

    return TLSArtifacts(
        certificate=str(cert),
        private_key=str(key),
        ca=str(ca),
        chain=[str(cert), *list({str(signing_cert), str(ca)})],
        signing_cert=str(signing_cert),
        signing_key=str(signing_key),
    )
