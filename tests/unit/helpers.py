#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

from dataclasses import dataclass
from datetime import timedelta

from charms.tls_certificates_interface.v4.tls_certificates import (
    generate_ca,
    generate_certificate,
    generate_csr,
    generate_private_key,
)


@dataclass
class TLSArtifacts:
    certificate: str
    private_key: str
    ca: str
    chain: list[str]
    signing_cert: str
    signing_key: str


def generate_tls_artifacts(
    common_name: str = "some-app/0",
    sans_dns: list[str] = ["localhost"],
    sans_ip: list[str] = ["127.0.0.1"],
    with_intermediate: bool = False,
) -> TLSArtifacts:
    """Generates necessary TLS artifacts for TLS tests.

    Args:
        common_name (str, optional): Certificate Subject Name. Defaults to "some-app/0".
        sans_dns (list[str], optional): List of SANS DNS addresses. Defaults to ["localhost"].
        sans_ip (list[str], optional): List of SANS IP addresses. Defaults to ["127.0.0.1"].
        with_intermediate (bool, optional): Whether or not should use and intermediate CA to sign the end cert. Defaults to False.

    Returns:
        TLSArtifacts: Object containing required TLS Artifacts.
    """
    validity = timedelta(days=365)

    # CA
    ca_key = generate_private_key()
    ca = generate_ca(private_key=ca_key, common_name="some-ca", validity=validity)
    signing_cert, signing_key = ca, ca_key

    # Intermediate?
    if with_intermediate:
        intermediate_key = generate_private_key()
        intermediate_csr = generate_csr(
            private_key=intermediate_key,
            common_name="some-intermediate",
        )
        intermediate_cert = generate_certificate(
            intermediate_csr, ca, ca_key, validity=validity, is_ca=True
        )
        signing_cert, signing_key = intermediate_cert, intermediate_key

    key = generate_private_key()
    csr = generate_csr(key, common_name=common_name, sans_dns=sans_dns, sans_ip=sans_ip)
    cert = generate_certificate(csr, signing_cert, signing_key, validity=validity)

    return TLSArtifacts(
        certificate=str(cert),
        private_key=str(key),
        ca=str(ca),
        chain=[str(cert), *list({str(signing_cert), str(ca)})],
        signing_cert=str(signing_cert),
        signing_key=str(signing_key),
    )
