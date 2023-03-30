# Charmed Kafka Operator

## Overview

The Charmed Kafka Operator delivers automated operations management from day 0 to day 2 on the [Apache Kafka](https://kafka.apache.org) event streaming platform. It is an open source, end-to-end, production ready data platform on top of cloud native technologies.

This operator charm comes with features such as:
- Fault-tolerance, replication, scalability and high-availability out-of-the-box.
- SASL/SCRAM auth for Broker-Broker and Client-Broker authenticaion enabled by default.
- Access control management supported with user-provided ACL lists.

The Kafka Operator uses the latest upstream Kafka binaries released by the The Apache Software Foundation that comes with Kafka, made available using the [`charmed-kafka` snap ](https://snapcraft.io/charmed-kafka) distributed by Canonical.

As currently Kafka requires a paired ZooKeeper deployment in production, this operator makes use of the [ZooKeeper Operator](https://github.com/canonical/zookeeper-operator) for various essential functions.

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

## Requirements

For production environments, it is recommended to deploy at least 5 nodes for Zookeeper and 3 for Kafka.
While the following requirements are meant to be for production, the charm can be deployed in much smaller environments.

- 64GB of RAM
- 24 cores
- 12 storage devices
- 10 GbE card

The charm is meant to be deployed using `juju>=2.9.37`.

## Usage

### Basic usage

The Kafka and ZooKeeper operators can both be deployed as follows:
```shell
$ juju deploy zookeeper --channel latest/edge -n 5
$ juju deploy kafka --channel latest/edge -n 3
```

After this, it is necessary to connect them:
```shell
$ juju relate kafka zookeeper
```

To watch the process, `juju status` can be used. Once all the units show as `active|idle` the credentials to access a broker can be queried with:
```shell
juju run-action kafka/leader get-admin-credentials --wait
```

Apache Kafka ships with `bin/*.sh` commands to do various administrative tasks, e.g `bin/kafka-config.sh` to update cluster configuration, `bin/kafka-topics.sh` for topic management, and many more! The Kafka Charmed Operator provides these commands to administrators to easily run their desired cluster configurations securely with SASL authentication, either from within the cluster or as an external client.

If you wish to run a command from the cluster, in order to (for example) list the current topics on the Kafka cluster, you can run:
```
BOOTSTRAP_SERVERS=$(juju run-action kafka/leader get-admin-credentials --wait | grep "bootstrap.servers" | cut -d "=" -f 2)
juju ssh kafka/leader 'charmed-kafka.topics --bootstrap-server $BOOTSTRAP_SERVERS --list --command-config /var/snap/charmed-kafka/common/client.properties'
```

Note that when no other application is related to Kafka, the cluster is secured-by-default and listeners are disabled, thus preventing any incoming connection. However, even for running the commands above, listeners must be enable. If there is no other application, deploy a `data-integrator` charm and relate it to Kafka, as outlined in the Relation section to enable listeners.

Available Kafka bin commands can be found with:
```
snap info charmed-kafka --channel latest/edge
```

### Replication
#### Scaling up
The charm can be scaled up using `juju add-unit` command.
```shell
juju add-unit kafka
```

To add a specific number of brokers, an extra argument is needed:
```shell
juju add-unit kafka -n <num_brokers_to_add>
```

#### Scaling down
To scale down the charm, use `juju remove-unit` command.
```shell
juju remove-unit <unit_name>
```

Even when scaling multiple units at the same time, the charm uses a rolling restart sequence to make sure the cluster stays available and healthy during the operation.

### Password rotation
#### Internal operator user
The operator user is used internally by the Charmed Kafka Operator, the `set-password` action can be used to rotate its password.
```shell
# to set a specific password for the operator user
juju run-action kafka/leader set-password password=<password> --wait

# to randomly generate a password for the operator user
juju run-action kafka/leader set-password --wait
```

### Storage support

Currently, the Charmed Kafka Operator supports 1 or more storage volumes. A 10G storage volume will be installed by default for `log.dirs`
This is used for logs storage, mounted on `/var/snap/kafka/common`

When storage is added or removed, the Kafka service will restart to ensure it uses the new volumes. Additionally, log + charm status messages will prompt users to manually reassign partitions so that the new storage volumes are populated. By default, Kafka will not assign partitions to new directories/units until existing topic partitions are assigned to it, or a new topic is created

## Relations

Supported [relations](https://juju.is/docs/olm/relations):

#### `kafka_client` interface:

The `kafka_client` interface is used with the `data-integrator` charm. This charm allows to automatically create and manage product credentials needed to authenticate with different kinds of data platform charmed products:

Deploy the data-integrator charm with the desired `topic-name` and user roles:
```shell
juju deploy data-integrator --channel edge
juju config data-integrator topic-name=test-topic extra-user-roles=producer,consumer
```

Relate the two applications with:
```shell
juju relate data-integrator kafka
```

To retrieve information, enter:
```shell
juju run-action data-integrator/leader get-credentials --wait
```

This should output something like:
```yaml
unit-data-integrator-0:
  UnitId: data-integrator/0
  id: "4"
  results:
    kafka:
      consumer-group-prefix: relation-27-
      endpoints: 10.123.8.133:19092
      password: ejMp4SblzxkMCF0yUXjaspneflXqcyXK
      tls: disabled
      username: relation-27
      zookeeper-uris: 10.123.8.154:2181,10.123.8.181:2181,10.123.8.61:2181/kafka
    ok: "True"
  status: completed
  timing:
    completed: 2023-01-27 14:22:51 +0000 UTC
    enqueued: 2023-01-27 14:22:50 +0000 UTC
    started: 2023-01-27 14:22:51 +0000 UTC
```

#### `tls-certificates` interface:

The `tls-certificates` interface is used with the `tls-certificates-operator` charm.

To enable TLS:

```shell
# deploy the TLS charm
juju deploy tls-certificates-operator --channel=edge
# add the necessary configurations for TLS
juju config tls-certificates-operator generate-self-signed-certificates="true" ca-common-name="Test CA"
# to enable TLS relate the two applications
juju relate tls-certificates-operator zookeeper
juju relate tls-certificates-operator kafka
```

Updates to private keys for certificate signing requests (CSR) can be made via the `set-tls-private-key` action.
```shell
# Updates can be done with auto-generated keys with
juju run-action kafka/0 set-tls-private-key --wait
juju run-action kafka/1 set-tls-private-key --wait
juju run-action kafka/2 set-tls-private-key --wait
```

Passing keys to external/internal keys should *only be done with* `base64 -w0` *not* `cat`. With three brokers this schema should be followed:
```shell
# generate shared internal key
openssl genrsa -out internal-key.pem 3072
# apply keys on each unit
juju run-action kafka/0 set-tls-private-key "internal-key=$(base64 -w0 internal-key.pem)"  --wait
juju run-action kafka/1 set-tls-private-key "internal-key=$(base64 -w0 internal-key.pem)"  --wait
juju run-action kafka/2 set-tls-private-key "internal-key=$(base64 -w0 internal-key.pem)"  --wait
```

To disable TLS remove the relation
```shell
juju remove-relation kafka tls-certificates-operator
juju remove-relation zookeeper tls-certificates-operator
```

Note: The TLS settings here are for self-signed-certificates which are not recommended for production clusters, the `tls-certificates-operator` charm offers a variety of configurations, read more on the TLS charm [here](https://charmhub.io/tls-certificates-operator)


## Monitoring

The Charmed Kafka Operator comes with the [JMX exporter](https://github.com/prometheus/jmx_exporter/).
The metrics can be queried by accessing the `http://<unit-ip>:9101/metrics` endpoints.

Additionally, the charm provides integration with the [Canonical Observability Stack](https://charmhub.io/topics/canonical-observability-stack).

Deploy cos-lite bundle in a Kubernetes environment. This can be done by following the
[deployment tutorial](https://charmhub.io/topics/canonical-observability-stack/tutorials/install-microk8s).
Since the Charmed Kafka Operator is deployed on a machine environment, it is needed to offer the endpoints
of the COS relations. The [offers-overlay](https://github.com/canonical/cos-lite-bundle/blob/main/overlays/offers-overlay.yaml)
can be used, and this step is shown in the COS tutorial.

Next, deploy [grafana-agent](https://charmhub.io/grafana-agent) and follow the
[tutorial](https://discourse.charmhub.io/t/using-the-grafana-agent-machine-charm/8896)
to relate it to the COS Lite offers.

Now, relate kafka with the grafana-agent:
```shell
juju relate kafka grafana-agent
```

After this is complete, Grafana will show two new dashboards: `Kafka Metrics` and `Node Exporter Kafka`

## Security
Security issues in the Charmed Kafka Operator can be reported through [LaunchPad](https://wiki.ubuntu.com/DebuggingSecurity#How%20to%20File). Please do not file GitHub issues about security issues.

## Performance Tuning
#### Virtual Memory Handling - Recommended
Kafka brokers make heavy use of the OS page cache to maintain performance. They never normally explicitly issue a command to ensure messages have been persisted to disk (`sync`), relying instead on the underlying OS to ensure that larger chunks (pages) of data are persisted from the page cache to the disk when the OS deems it efficient and/or necessary to do so. As such, there are a range of runtime kernel parameter tuning that are recommended to set on machines running Kafka to improve performance.

In order to configure these settings, one can write them to `/etc/sysctl.conf` using `sudo echo $SETTING >> /etc/sysctl.conf`. Note that the settings shown below are simply sensible defaults that may not apply to every workload:
```bash
# ensures low likelihood of memory being assigned to swap-space rather than drop pages from the page cache
vm.swappiness=1

# higher ratio results in less frequent disk flushes and better disk I/O performance
vm.dirty_ratio=80
vm.dirty_background_ratio=5
```

#### Memory Maps - Recommended
Each Kafka log segment requires an `index` file and a `timeindex` file, both requiring 1 map area. The default OS maximum number of memory map areas a process can have is set by `vm.max_map_count=65536`. For production deployments with a large number of partitions and log-segments, it is likely to exceed the maximum OS limit.

It is recommended to set the mmap number sufficiently higher than the number of memory mapped files. This can also be written to `/etc/sysctl.conf`:
```bash
vm.max_map_count=<new_mmap_value>
```

#### File Descriptors - Recommended
Kafka uses file descriptors for log segments and open connections. If a broker hosts many partitions, keep in mind that the broker requires **at least** `(number_of_partitions)*(partition_size/segment_size)` file descriptors to track all the log segments and number of connections.

In order to configure those limits, update the values and add the following to `/etc/security/limits.d/root.conf`:
```bash
#<domain> <type> <item> <value>
root soft nofile 262144
root hard nofile 1024288
```

#### Networking - Optional
If you are expecting a large amount of network traffic, kernel parameter tuning may help meet that expected demand. These can also be written to `/etc/sysctl.conf`:
```bash
# default send socket buffer size
net.core.wmem_default=
# default receive socket buffer size
net.core.rmem_default=
# maximum send socket buffer size
net.core.wmem_max=
# maximum receive socket buffer size
net.core.rmem_max=
# memory reserved for TCP send buffers
net.ipv4.tcp_wmem=
# memory reserved for TCP receive buffers
net.ipv4.tcp_rmem=
# TCP Window Scaling option
net.ipv4.tcp_window_scaling=
# maximum number of outstanding TCP connection requests
net.ipv4.tcp_max_syn_backlog=
# maximum number of queued packets on the kernel input side (useful to deal with spike of network requests).
net.core.netdev_max_backlog=
```

## Contributing

Please see the [Juju SDK docs](https://juju.is/docs/sdk) for guidelines on enhancements to this charm following best practice guidelines, and [CONTRIBUTING.md](https://github.com/canonical/kafka-operator/blob/main/CONTRIBUTING.md) for developer guidance.


## License
The Charmed Kafka Operator is free software, distributed under the Apache Software License, version 2.0. See [LICENSE](https://github.com/canonical/kafka-operator/blob/main/LICENSE) for more information.
