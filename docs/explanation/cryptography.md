(explanation-cryptography)=
# Cryptography

This document describes the cryptography used by Charmed Apache Kafka K8s.

## Resource checksums

Charmed Apache Kafka K8s and Charmed Apache ZooKeeper K8s operators use pinned revisions of their respective rocks to provide reproducible and secure environments.

The [Charmed Apache Kafka rock](https://github.com/canonical/charmed-kafka-rock/pkgs/container/charmed-kafka) and 
[Charmed Apache ZooKeeper rock](https://github.com/canonical/charmed-zookeeper-rock/pkgs/container/charmed-zookeeper) are OCI images
derived from their respective snaps. These snaps package the Apache Kafka and Apache ZooKeeper workloads along with the necessary dependencies and utilities required for the operators' lifecycle. See the snap contents for the [Charmed Apache Kafka](https://github.com/canonical/charmed-kafka-snap/blob/3/edge/snap/snapcraft.yaml) and [Charmed Apache ZooKeeper](https://github.com/canonical/charmed-zookeeper-snap/blob/3/edge/snap/snapcraft.yaml).

Every artefact bundled into the Charmed Apache Kafka and Charmed Apache ZooKeeper snaps is verified against their MD5, SHA256, or SHA512 checksum after download.
The installation of certified snaps into the rock is ensured by snap primitives that verify their
Squashfs file systems images GPG signature. For more information on the snap verification process, refer to the [Snapcraft documentation](https://snapcraft.io/docs/assertions).

## Sources verification

Charmed Apache Kafka K8s sources are stored in:

* GitHub repositories for snaps, rocks and charms
* Launchpad repositories for the Apache Kafka and Apache ZooKeeper upstream fork used for building their respective distributions

### Launchpad

Distributions are built using private repositories only, hosted as part of the [SOSS namespace](https://launchpad.net/soss) (private) to eventually
integrate with Canonical's standard process for fixing CVE.
Branches associated with releases are mirrored to a public repository, hosted in the [Data Platform namespace](https://launchpad.net/~data-platform)
to also provide the community with the patched source code.

### GitHub

All Apache Kafka and Apache ZooKeeper artefacts built by Canonical are published and released 
programmatically using release pipelines implemented via GitHub Actions.
Distributions are published as both GitHub and Launchpad releases via the [central-uploader repository](https://github.com/canonical/central-uploader), while 
charms, snaps and rocks are published using the workflows of their respective repositories. 

All repositories in GitHub are set up with branch protection rules, requiring:

* new commits to be merged to main branches via pull request with at least 2 approvals from repository maintainers
* new commits to be signed (e.g. using GPG keys)
* developers to sign the [Canonical Contributor License Agreement (CLA)](https://ubuntu.com/legal/contributors)

## Encryption

Charmed Apache Kafka K8s can be used to deploy a secure Apache Kafka cluster on K8s that provides encryption-in-transit capabilities out of the box 
for:

* Interbroker communications
* Apache ZooKeeper connection
* External client connection 

To set up a secure connection Charmed Apache Kafka K8s and Charmed Apache ZooKeeper K8s need to be integrated with TLS Certificate Provider charms, e.g., 
`self-signed-certificates` operator. Certificate Singing Requests (CSRs) are generated for every unit using the `tls_certificates_interface` library that uses the `cryptography` Python library to create X.509 compatible certificates.
The CSR is signed by the TLS Certificate Provider, returned to the units, and stored in a password-protected Keystore file.
The password of the Keystore is stored in Juju secrets.
The relation also provides the CA certificate, which is loaded into a password-protected Truststore file.

When encryption is enabled, hostname verification is turned on for client connections, including inter-broker communication. The cipher suite can be customised by specifying a list of allowed cipher suites for external clients and Apache ZooKeeper connections. This is done using the charm configuration options `ssl_cipher_suites` and `zookeeper_ssl_cipher_suites`, respectively (see [reference documentation](https://charmhub.io/kafka-k8s/configurations)).

Encryption at rest is currently not supported, although it can be provided by the substrate (cloud or on-premises).

## Authentication

In Charmed Apache Kafka K8s, authentication layers can be enabled for:

1. Apache ZooKeeper connections
2. Apache Kafka inter-broker communication
3. Apache Kafka clients

### Apache Kafka authentication to Apache ZooKeeper

Authentication to Apache ZooKeeper is based on Simple Authentication and Security Layer (SASL) using digested MD5 hashes of
username and password, and implemented both for client-server (with Apache Kafka) and server-server communication.
Username and passwords are exchanged using peer relations among Apache ZooKeeper units and using normal relations between Apache Kafka and Apache ZooKeeper.
Juju secrets are used for exchanging credentials.

Usernames and passwords for different users are stored in Apache ZooKeeper servers in a [JAAS](https://docs.oracle.com/en/java/javase/11/security/java-authentication-authorization-service-jaas-reference-guide.html) configuration file in plain text format. 
Permissions on the file are restricted to the root user only.

### Apache Kafka interbroker authentication

Authentication among brokers is based on the SCRAM-SHA-512 protocol. Usernames and passwords are exchanged via peer relations, using Juju secrets.

The Apache Kafka username and password, used by brokers to authenticate each other, are stored both in an Apache ZooKeeper znode and in a JAAS configuration file on the Apache Kafka server in plain text format.

### Client authentication to Apache Kafka

Clients can authenticate to Kafka using:

1. username and password exchanged using SCRAM-SHA-512 protocols 
2. client certificates or CA (mTLS)

When using SCRAM, usernames and passwords are stored in Apache ZooKeeper to be used by the Apache Kafka processes, 
in peer-relation data to be used by the Apache Kafka charm 
and in external relation to be shared with client applications. 
Juju secrets are used for storing the credentials.

When using mTLS, client certificates are loaded into a `tls-certificates` operator and provided to the Charmed Apache Kafka K8s via the plain-text unencrypted 
relation. Certificates are stored in the password-protected Truststore file.
