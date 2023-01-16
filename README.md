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

### Secure-by-default, authenticated cluster administration
Apache Kafka ships with `bin/*.sh` commands to do various administrative tasks, e.g `bin/kafka-config.sh` to update cluster configuration, `bin/kafka-topics.sh` for topic management, and many more! The Kafka Charmed Operator provides these commands to administrators to easily run their desired cluster configurations securely with SASL authentication, either from within the cluster or as an external client.

To run commands from within the cluster, the charm makes available a `client.properties` file with all the necessary configuration to run a `KafkaClient`. One can retrieve `admin` credentials with:
```
juju run-action kafka/leader get-admin-credentials
```

If you wish to run a command from the cluster, in order to (for example) list the current topics on the Kafka cluster, you can run:
```
BOOTSTRAP_SERVERS=$(juju run-action kafka/leader get-admin-credentials --wait | grep "bootstrap.servers" | cut -d "=" -f 2)
juju ssh kafka/leader 'kafka.topics --bootstrap-server $BOOTSTRAP_SERVERS --list --command-config /var/snap/kafka/common/client.properties'
```

Available Kafka bin commands can be found with:
```
snap info kafka --channel rock/edge
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
