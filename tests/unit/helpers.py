#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

from dataclasses import dataclass

from charms.tls_certificates_interface.v3.tls_certificates import (
    generate_ca,
    generate_certificate,
    generate_csr,
    generate_private_key,
)
from cryptography import x509


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
    # CA
    ca_key = generate_private_key()
    ca = generate_ca(private_key=ca_key, subject="some-ca")
    signing_cert, signing_key = ca, ca_key

    # Intermediate?
    if with_intermediate:
        intermediate_key = generate_private_key()
        key_usage_ext = x509.KeyUsage(
            digital_signature=True,
            content_commitment=False,
            key_encipherment=False,
            data_encipherment=False,
            key_agreement=False,
            key_cert_sign=True,
            crl_sign=True,
            encipher_only=False,
            decipher_only=False,
        )
        intermediate_csr = generate_csr(
            private_key=intermediate_key,
            subject="some-intermediate",
            additional_critical_extensions=[key_usage_ext],
        )
        intermediate_cert = generate_certificate(intermediate_csr, ca, ca_key)
        signing_cert, signing_key = intermediate_cert, intermediate_key

    key = generate_private_key()
    csr = generate_csr(key, subject=subject, sans_dns=sans_dns, sans_ip=sans_ip)
    cert = generate_certificate(csr, signing_cert, signing_key)

    return TLSArtifacts(
        certificate=cert.decode("utf-8"),
        private_key=key.decode("utf-8"),
        ca=ca.decode("utf-8"),
        chain=[cert.decode("utf-8"), *list({signing_cert.decode("utf-8"), ca.decode("utf-8")})],
        signing_cert=signing_cert.decode("utf-8"),
        signing_key=signing_key.decode("utf-8"),
    )
