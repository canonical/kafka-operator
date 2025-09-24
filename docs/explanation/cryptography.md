(explanation-cryptography)=
# Cryptography

This document describes the cryptography used by Charmed Apache Kafka.

## Resource checksums

Charmed Apache Kafka uses a pinned snap to provide reproducible and secure environments.

The [Charmed Apache Kafka snap](https://snapstore.io/charmed-kafka) packages the Apache Kafka workload along with the necessary dependencies and utilities for operator lifecycle management.
For details on the contents of the snap, refer to the `snapcraft.yaml` file in the source code: [Charmed Apache Kafka snap contents](https://github.com/canonical/charmed-kafka-snap/blob/4/edge/snap/snapcraft.yaml).

Every artefact included in the snap is verified against its SHA-256 or SHA-512 checksum after download.

## Sources verification

Charmed Apache Kafka sources are stored in:

* GitHub repositories for snaps, rocks and charms
* Launchpad repositories for the Apache Kafka upstream fork for building from the source

### Launchpad

Distributions are built using private repositories only, hosted as part of the [SOSS namespace](https://launchpad.net/soss) (private) to eventually
integrate with Canonical's standard process for fixing CVE.
Branches associated with releases are mirrored to a public repository, hosted in the [Data Platform namespace](https://launchpad.net/~data-platform)
to also provide the community with the patched source code.

### GitHub

All Apache Kafka artefacts built by Canonical are published and released programmatically using GitHub Actions release pipelines. 
Distributions are published as both GitHub and Launchpad releases via the [central-uploader repository](https://github.com/canonical/central-uploader), while 
charms, snaps and rocks are published using the workflows of their respective repositories. 

All repositories in GitHub are set up with branch protection rules, requiring:

* new commits to be merged to main branches via pull request with at least 2 approvals from repository maintainers
* new commits to be signed (e.g. using GPG keys)
* developers to sign the [Canonical Contributor License Agreement (CLA)](https://ubuntu.com/legal/contributors)

## Encryption

Charmed Apache Kafka can be used to deploy a secure Apache Kafka cluster that provides encryption-in-transit capabilities out of the box 
for:

* Inter-broker communications
* Broker-controller communications
* Client connections

By default, a Charmed Apache Kafka application will always use auto-generated self-signed TLS/SSL certificates for inter-broker and broker-controller communications.
To support encrypted client connections, a Charmed Apache Kafka application needs to be integrated with TLS Certificate Provider charm, e.g. 
`self-signed-certificates` operator. Certificate Singing Requests (CSRs) are generated for every unit using the `tls_certificates_interface` library that uses the `cryptography` 
Python library to create X.509 compatible certificates. The CSR is signed by the TLS Certificate Provider, returned to the units, and 
stored in a password-protected PKCS 12 keystore file. The password of the keystore is stored in Juju secrets.
The integration also provides the CA certificate, which is loaded into a password-protected JKS truststore file.

When encryption is enabled, hostname verification is turned on for client connections, including both inter-broker and broker-controller communications. The cipher suite can 
be customised by specifying a list of allowed cipher suites for external clients. This is done using the charm configuration option
`ssl_cipher_suites` (see [reference documentation](https://charmhub.io/kafka/configurations)). 

Encryption-at-rest is currently not supported, although it can be provided by the substrate (cloud or on-premises).

## Authentication

In Charmed Apache Kafka, authentication layers can be enabled for:

1. Inter-broker communications
2. Broker-controller communications
3. Clients connections

### Inter-broker and broker-controller authentication

Authentication between brokers and between brokers and KRaft controllers are based on the SCRAM-SHA-512 protocol. Usernames and passwords are exchanged via Juju secrets.

The Apache Kafka username and password, used by brokers and controllers to authenticate one another, are stored in JAAS configuration files on the Charmed Apache Kafka units in plain text format.

These files are readable and writable by `root` (as it is created by the charm) and readable by the snap-internal `_daemon_` user running the Apache Kafka server snap commands.

### Client authentication to Apache Kafka

Clients can authenticate to Apache Kafka using:

1. username and password exchanged using SCRAM-SHA-512 protocols
2. client certificates or CA (mTLS)
3. OAuth Authentication using [Hydra](https://discourse.charmhub.io/t/how-to-connect-to-kafka-using-hydra-as-oidc-provider/14610) or [Google](https://discourse.charmhub.io/t/how-to-connect-to-kafka-using-google-as-oidc-provider/14611)

When using SCRAM, usernames and passwords are stored in the KRaft controller metadata logs, in plain text in configuration files on the broker and controller units, and in Juju secrets. 
When using mTLS, client certificates provided to the Apache Kafka cluster via Juju secrets by related charms are stored in password-protected JKS truststores.
