# Cryptography

## Resource checksums

Every version of the Charmed Kafka and Charmed ZooKeeper operators install a pinned revision of the Charmed Kafka snap
and Charmed ZooKeeper, respectively, in order to 
provide reproducible and secure environments. The Charmed Kafka snap and Charmed ZooKeeper snap package the 
Kafka and ZooKeeper workload together with 
a set of dependencies and utilities required by the lifecycle of the operators. 
Every artifact bundled into the Charmed Kafka snap and Charmed ZooKeeper snap are verified against their checksum. 

## Sources verification

Charmed Kafka and Charmed ZooKeeper artifacts are published programmatically using release pipelines implemented via GitHub Actions of the 
associated repositories. 
All repositories containing the source code of the Charmed Kafka project (i.e. charm and snap codebases) are set up with 

* Branch protection rules requiring additional commits to be merged via Pull-Request with at least 2 approvals from repository maintainers
* Signed commits requirements (using GPG keys)
* Requiring developers to sign CLA agreement

## Encryption

The Charmed Kafka operator allow to deploy a secure Kafka cluster providing encryption-in-transit capabilities out of the box 
for
* Interbroker communications
* ZooKeeper connection
* External client connection 

In order to set up secure connection Kafka and ZooKeeper applications need to be integrated with TLS Certificate Provider charms, e.g. 
`self-signed-certificates` operator. CSRs are generated for every unit using `tls_certificates_interface` library that uses `cryptography` 
python library to create X.509 compatible certificates. The CSR is signed by the TLS Certificate Provider and returned to the units, and 
stored in a password-protected Keystore file. The password of the Keystore is stored in Juju secrets starting from revision 168 on Kafka 
and revision 130 on ZooKeeper. The relation provides also the certificate for the CA to be loaded in a password-protected Truststore file.

When encryption is enabled, hostname verification is turned on for client connections, including inter-broker communication. 

Encryption at rest is currently not supported, although it can be provided by the substrate (cloud or on-premises).

## Authentication

There exists 3 layers of authentication in the Charmed Kafka solution:

1. ZooKeeper authentication
2. Kafka inter broker authentication 
3. Client authentication to Kafka

### Kafka authentication to ZooKeeper

Authentication to ZooKeeper is based on Simple Authentication and Security Layer (SASL) using digested hash (using md5) of
username and password, and implemented both for client-server (with Kafka) and server-server communication.
Username and passwords are exchanged using peer relations among ZooKeeper units and using normal relations between Kafka and ZooKeeper.
Juju secrets are used for exchanging credentials starting from revision 168 on Kafka and revision 130 on ZooKeeper.

Username and password for the different users are stored in ZooKeeper servers in a JAAS configuration file in plain format. 
Permission on the file is restricted to the root user. 

### Kafka Inter-broker authentication

Authentication among brokers is based on SCRAM-SHA-512 protocol. Username and passwords are exchanged 
via peer relations, using Juju secrets from revision 168 on Kafka

Username and password are stored in ZooKeeper servers in a JAAS configuration file in plain format. The file needs to be readable and
writable by root (as it is created by the charm), and be readable by the `snap_daemon` user running the Kafka server snap commands.

### Client authentication to Kafka

Clients can authenticate to Kafka using:

1. username and password exchanged using SCRAM-SHA-512 protocols 
2. client certificates (mTLS)

When using SCRAM, username and passwords are stored in ZooKeeper to be used by the Kafka processes, 
in peer-relation data to be used by the Kafka charm and in external relation to be shared with client applications. 
Starting from revision 168 on Kafka, Juju secrets are used for storing the credentials in place of plain unencrypted text.

When using mTLS, client certificates are loaded into a `tls-certificates` operator and provided to the Kafka charm via the plain-text unencrypted 
relation. Certificates are stored in the password-protected Truststore file.