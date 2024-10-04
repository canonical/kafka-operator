# Cryptography

This document describes cryptography used by Charmed Kafka.

## Resource checksums
Every version of the Charmed Kafka and Charmed ZooKeeper operators install a pinned revision of the Charmed Kafka snap
and Charmed ZooKeeper, respectively, in order to 
provide reproducible and secure environments. The [Charmed Kafka snap](https://snapstore.io/charmed-kafka) and [Charmed ZooKeeper snap](https://snapstore.io/charmed-zookeeper) package the 
Kafka and ZooKeeper workload together with 
a set of dependencies and utilities required by the lifecycle of the operators (see [Charmed Kafka snap contents](https://github.com/canonical/charmed-kafka-snap/blob/3/edge/snap/snapcraft.yaml) and [Charmed ZooKeeper snap contents](https://github.com/canonical/charmed-zookeeper-snap/blob/3/edge/snap/snapcraft.yaml)).
Every artifact bundled into the Charmed Kafka snap and Charmed ZooKeeper snap is verified against their SHA256 or SHA512 checksum after download. 

## Sources verification
Charmed Kafka sources are stored in:

* GitHub repositories for snaps, rocks and charms
* LaunchPad repositories for the Kafka and ZooKeeper upstream fork used for building their respective distributions

### LaunchPad
Distributions are built using private repositories only, hosted as part of the [SOSS namespace](https://launchpad.net/soss) to eventually
integrate with Canonical's standard process for fixing CVEs. 
Branches associated with releases are mirrored to a public repository, hosted in the [Data Platform namespace](https://launchpad.net/~data-platform) 
to also provide the community with the patched source code. 

### GitHub
All Charmed Kafka and Charmed ZooKeeper artifacts are published and released 
programmatically using release pipelines implemented via GitHub Actions. 
Distributions are published as both GitHub and LaunchPad releases via the [central-uploader repository](https://github.com/canonical/central-uploader), while 
charms, snaps and rocks are published using the workflows of their respective repositories. 

All repositories in GitHub are set up with branch protection rules, requiring:

* new commits to be merged to main branches via Pull-Request with at least 2 approvals from repository maintainers
* new commits to be signed (e.g. using GPG keys)
* developers to sign the [Canonical Contributor License Agreement (CLA)](https://ubuntu.com/legal/contributors)

## Encryption
The Charmed Kafka operator can be used to deploy a secure Kafka cluster that provides encryption-in-transit capabilities out of the box 
for:

* Interbroker communications
* ZooKeeper connection
* External client connection 

In order to set up secure connection Kafka and ZooKeeper applications need to be integrated with TLS Certificate Provider charms, e.g. 
`self-signed-certificates` operator. CSRs are generated for every unit using `tls_certificates_interface` library that uses `cryptography` 
python library to create X.509 compatible certificates. The CSR is signed by the TLS Certificate Provider and returned to the units, and 
stored in a password-protected Keystore file. The password of the Keystore is stored in Juju secrets starting from revision 168 on Kafka 
and revision 130 on ZooKeeper. The relation provides also the certificate for the CA to be loaded in a password-protected Truststore file.

When encryption is enabled, hostname verification is turned on for client connections, including inter-broker communication. Cipher suite can 
be customized by providing a list of allowed cipher suite to be used for external clients and zookeeper connections, using the charm config options
`ssl_cipher_suites`  and `zookeeper_ssl_cipher_suites` config options respectively. Please refer to the [reference documentation](https://charmhub.io/kafka/configurations)
for more information. 

Encryption at rest is currently not supported, although it can be provided by the substrate (cloud or on-premises).

## Authentication
In the Charmed Kafka solution, authentication layers can be enabled for

1. ZooKeeper connections
2. Kafka inter broker communication 
3. Kafka Clients

### Kafka authentication to ZooKeeper
Authentication to ZooKeeper is based on Simple Authentication and Security Layer (SASL) using digested MD5 hashes of
username and password, and implemented both for client-server (with Kafka) and server-server communication.
Username and passwords are exchanged using peer relations among ZooKeeper units and using normal relations between Kafka and ZooKeeper.
Juju secrets are used for exchanging credentials starting from revision 168 on Kafka and revision 130 on ZooKeeper.

Username and password for the different users are stored in ZooKeeper servers in a JAAS configuration file in plain format. 
Permission on the file is restricted to the root user. 

### Kafka Inter-broker authentication
Authentication among brokers is based on SCRAM-SHA-512 protocol. Username and passwords are exchanged 
via peer relations, using Juju secrets from revision 168 on Charmed Kafka.

Kafka username and password used by brokers to authenticate one another are stored 
both in a ZooKeeper zNode and in a JAAS configuration file in the Kafka server in plain format. 
The file needs to be readable and
writable by root (as it is created by the charm), and be readable by the `snap_daemon` user running the Kafka server snap commands.

### Client authentication to Kafka
Clients can authenticate to Kafka using:

1. username and password exchanged using SCRAM-SHA-512 protocols 
2. client certificates or CAs (mTLS)

When using SCRAM, username and passwords are stored in ZooKeeper to be used by the Kafka processes, 
in peer-relation data to be used by the Kafka charm and in external relation to be shared with client applications. 
Starting from revision 168 on Kafka, Juju secrets are used for storing the credentials in place of plain unencrypted text.

When using mTLS, client certificates are loaded into a `tls-certificates` operator and provided to the Kafka charm via the plain-text unencrypted 
relation. Certificates are stored in the password-protected Truststore file.