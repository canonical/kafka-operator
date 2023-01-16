## Kafka Operator - a Charmed Operator for running Apache Kafka from Canonical
This repository hosts the Machine Python Operator for [Apache Kafka](https://kafka.apache.org).
The Kafka Operator is a Python script that uses the latest upstream Kafka binaries released by the The Apache Software Foundation that comes with Kafka, made available using the [Kafka Snap](https://snapcraft.io/kafka) distributed by Canonical.

As currently Kafka requires a paired ZooKeeper deployment in production, this operator makes use of the [ZooKeeper Operator](https://github.com/canonical/zookeeper-operator) for various essential functions. 

### How to deploy
The Kafka and ZooKeeper operators can both be deployed and connected to each other using the Juju command line as follows:

```bash
$ juju deploy zookeeper -n 3
$ juju deploy kafka -n 3
$ juju relate kafka zookeeper
```

## A fast and fault-tolerant, real-time event streaming platform!
Manual, Day 2 operations for deploying and operating Apache Kafka, topic creation, client authentication, ACL management and more are all handled automatically using the [Juju Operator Lifecycle Manager](https://juju.is/docs/olm).

### Key Features
- SASL/SCRAM auth for Broker-Broker and Client-Broker authenticaion enabled by default.
- Access control management supported with user-provided ACL lists.
- Fault-tolerance, replication and high-availability out-of-the-box.
- Smooth topic-creation through [Juju Actions](https://juju.is/docs/olm/working-with-actions) and [application relations](https://juju.is/docs/olm/relations)

#### **rolling-restart-unit Action**
Manually triggers a rolling restart for specified units. The unit that this action runs on will be restarted, ensuring that no other application units are restarting at the same time. 

Must be ran on each unit separately.

##### Example Usage
To restart the current Kafka Leader, run:
```
juju run-action kafka/leader rolling-restart-unit
```

#### **set-password Action**
Change an internal system user's password. It is for internal charm users and SHOULD NOT be used by applications.

This action must be called on the leader unit.

##### Params
- **password** string
    The password will be auto-generated if this option is not specified.
- **username** string
    The username, the default value 'operator'. Possible values - `admin`, `sync`

##### Example Usage
To update the `admin` user password, run:
```
juju run-action kafka/leader set-password --params username=admin --params password=thisisapassword --wait
```

#### **set-tls-private-key Action**
Sets the private key identifying the target unit, which will be used for certificate signing requests (CSR). When updated, certificates will be reissued to the unit.

Must be ran on each unit separately.
Requires a valid relation to an application providing the [`certificates`](https://github.com/canonical/charm-relation-interfaces/tree/main/interfaces/tls_certificates/v1) relation interface. 

##### Params
- **internal-key** string
    The content of private key for internal communications with clients. Content will be auto-generated if this option is not specified.
    Can be raw string, or base64 encoded.

##### Example Usage
To update the private-key for the leader unit to a specific key, run:
```
juju run-action kafka/leader set-tls-private-key --params internal-key=<BASE64 STRING> --wait
```

#### **get-admin-credentials Action**
Gets administrator authentication credentials for client commands.

Kafka ships with `bin/*.sh` commands to do various administrative tasks. The returned `client_properties`, `username` and `password` can be used to run Kafka bin commands using `--bootstrap-server` and `--command-config` for admin level administration.

This action must be called on the leader unit.

##### Example Usage
To get the current `admin` SASL credentials, run:
```
juju run-action kafka/leader get-admin-credentials --wait
```
This will return something similar to:
```
results:
  client-properties: |-
    sasl.mechanism=SCRAM-SHA-512
    security.protocol=SASL_SSL
    sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="admin" password="E1RbjO78TUX5L3M428BTpdbEyJb1pqTJ";
    bootstrap.servers=10.3.238.51:9092
  password: E1RbjO78TUX5L3M428BTpdbEyJb1pqTJ
  username: admin
```

### Checklist
- [x] Super-user creation
- [x] Inter-broker auth
- [x] Horizontally scale brokers
- [x] Username/Password creation for related applications
- [x] Automatic topic creation with associated user ACLs
- [x] Persistent storage support with [Juju Storage](https://juju.is/docs/olm/defining-and-using-persistent-storage)
- [x] TLS/SSL encrypted connections
- [ ]  mTLS
- [ ] Multi-application clusters
- [ ] Partition rebalancing during broker scaling

### Contributing
This charm is still in active development. If you would like to contribute, please refer to [CONTRIBUTING.md](https://github.com/canonical/kafka-operator/blob/main/CONTRIBUTING.md)
