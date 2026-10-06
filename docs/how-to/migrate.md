(how-to-cluster-replication-migrate-a-cluster)=
# Migrate from a non-charmed Apache Kafka

This How-To guide covers executing a cluster migration to a Charmed Apache Kafka K8s deployment using MirrorMaker 2.0.

The MirrorMaker runs on the new (destination) cluster as a process on each Juju unit in an active/passive setup. It acts as a consumer from an existing cluster (source) and a producer to the Charmed Apache Kafka K8s cluster (target). Data and consumer offsets for all existing topics will be synced **one-way** in parallel (one process on each unit) until both clusters are in-sync, with all data replicated across both in real-time.

## MirrorMaker2 overview

Under the hood, MirrorMaker uses Kafka Connect source connectors to replicate data, those being the following:

- **MirrorSourceConnector** - replicates topics from an original cluster to a new cluster. It also replicates ACLs and is necessary for the MirrorCheckpointConnector to run
- **MirrorCheckpointConnector** - periodically tracks offsets. If enabled, it also synchronises consumer group offsets between the original and new clusters
- **MirrorHeartbeatConnector** - periodically checks connectivity between the original and new clusters

Together, they are used for cluster->cluster replication of topics, consumer groups, topic configuration and ACLs, preserving partitioning and consumer offsets. For more detail on MirrorMaker internals, consult the [Apache Kafka documentation on replication](https://kafka.apache.org/39/operations/geo-replication-cross-cluster-data-mirroring/) and the [MirrorMaker 2.0 KIP](https://cwiki.apache.org/confluence/display/KAFKA/KIP-382%3A+MirrorMaker+2.0). In practice, it allows one to sync data one way between two live Apache Kafka clusters with minimal impact on the ongoing production service.

In short, MirrorMaker runs as a distributed service on the new cluster that may not yet be serving traffic to external clients. MirrorMaker consumes all topics, groups and offsets from the still-active original cluster in production to produce them one way on the new one.

The original, in-production cluster is referred to as an ‘active’ cluster, and the new cluster still waiting to serve external clients is ‘passive’. The MirrorMaker service can be configured using a configuration similar to the one available for Kafka Connect.

```{note}
For a brief explanation of how MirrorMaker works, see the [MirrorMaker explanation](explanation-mirrormaker2-0) page.
```

## Pre-requisites

To migrate a cluster we need:

- An "old" existing Apache Kafka cluster to migrate from.
  - The cluster needs to be reachable from/to the new Apache Kafka cluster.
- A bootstrapped Juju K8s cloud running Charmed Apache Kafka K8s to migrate to. For guidance on how to deploy a new Charmed Apache Kafka K8s, see:
  - The [Charmed Apache Kafka K8s Tutorial](tutorial-index)
  - The [How to deploy guide](how-to-deploy-deploy-anywhere) for Charmed Apache Kafka K8s
- The CLI tool `yq` - [GitHub repository](https://github.com/mikefarah/yq)
  - `snap install yq --channel=v3/stable`

## Get cluster details and admin credentials

By design, the `kafka` charm will not expose any available connections until integrated with a client. In this case, we deploy `data-integrator` charms and integrate them to each `kafka` application, requesting `admin` level privileges:

```bash
juju deploy data-integrator --channel=edge -n 1 --config extra-user-roles="admin" --config topic-name="default"
juju integrate kafka-k8s data-integrator
```
<!-- Do we need the `edge` track in the above? -->

When the `data-integrator` charm integrates with a `kafka` application on the `kafka-client` relation interface, passing `extra-user-roles=admin`, a new user with `super.user` permissions will be created on that cluster, with the charm passing back the credentials and broker addresses in the relation data to the `data-integrator`.
As we will need full access to both clusters, we must grab these newly generated authorisation credentials from the `data-integrator`.

SASL credentials to connect to the target Charmed Apache Kafka K8s cluster:

```bash
export NEW_USERNAME=$(juju show-unit data-integrator/0 | yq -r '.. | .username? // empty')
export NEW_PASSWORD=$(juju show-unit data-integrator/0 | yq -r '.. | .password? // empty')
```

List of bootstrap-server IPs:

```bash
export NEW_SERVERS=$(juju show-unit data-integrator/0 | yq -r '.. | .endpoints? // empty')
```

Building full `sasl.jaas.config` for authorisation:

```bash
export NEW_SASL_JAAS_CONFIG="org.apache.kafka.common.security.scram.ScramLoginModule required username=\""${NEW_USERNAME}"\" password=\""${NEW_PASSWORD}\"\;
```

## Required source cluster credentials

MirrorMaker needs full `super.user` permissions on **BOTH** clusters. It supports every possible `security.protocol` supported by Apache Kafka. In this guide, we will make the assumption that the source cluster is using `SASL_PLAINTEXT` authentication, as such, the required information is as follows:

- `OLD_SERVERS` -- comma-separated list of Apache Kafka server IPs and ports to connect to
- `OLD_SASL_USERNAME` -- string of `sasl.jaas.config` property

```{note}
For `SSL` or `SASL_SSL` authentication, see the configuration options supported by Kafka Connect in the [Apache Kafka documentation](https://kafka.apache.org/39/configuration/kafka-connect-configs/).
```

## Creating `mm2.properties` file on the Apache Kafka cluster

MirrorMaker takes a `.properties` file for its configuration to fine-tune behaviour. See below an example `mm2.properties` file that can be placed on each of the Apache Kafka units using the above credentials:

```properties
# Aliases for each cluster, can be set to any unique alias
clusters = old,new

# Specifies that data from 'old' should be consumed and produced to 'new', and NOT visa-versa, i.e 'active/passive' setup
old->new.enabled = true
new->old.enabled = false

# comma-separated list of kafka server IPs and ports to connect from both clusters
old.bootstrap.servers=$OLD_SERVERS
new.bootstrap.servers=$NEW_SERVERS

# sasl authentication config for each cluster, in this case using the 'admin' users created by the integrator charm for Charmed Apache Kafka K8s
old.sasl.jaas.config=$OLD_SASL_JAAS_CONFIG
new.sasl.jaas.config=$NEW_SASL_JAAS_CONFIG

# if not deployed with TLS, Charmed Apache Kafka K8s uses SCRAM-SHA-512 for SASL auth, with a SASL_PLAINTEXT listener
sasl.mechanism=SCRAM-SHA-512
security.protocol=SASL_PLAINTEXT

# keeps topic names consistent across clusters - see https://kafka.apache.org/30/javadoc/org/apache/kafka/connect/mirror/IdentityReplicationPolicy.html
replication.policy.class=org.apache.kafka.connect.mirror.IdentityReplicationPolicy

# pattern match for replicating all topics and all consumer groups
topics=.*
groups=.*

# the expected number of concurrent MirrorMaker tasks, usually set to match number of physical cores on the target cluster
tasks.max=3

# the new replication.factor for topics produced to the target cluster
replication.factor=2

# allows new topics and groups created mid-migration, to be copied
refresh.topics.enabled=true
sync.group.offsets.enabled=true
sync.topic.configs.enabled=true
refresh.topics.interval.seconds=5
refresh.groups.interval.seconds=5
sync.group.offsets.interval.seconds=5
emit.checkpoints.interval.seconds=5

# filters out records from aborted transactions
old.consumer.isolation.level=read_committed
new.consumer.isolation.level=read_committed

# Specific Connector configuration for ensuring Exactly-Once-Delivery (EOD)
# NOTE - EOD support guarantees released with Apache Kafka 3.5.0 so some of these options may not work as expected
old.producer.enable.idempotence=true
new.producer.enable.idempotence=true
old.producer.acks=all
new.producer.acks=all
# old.exactly.once.support = enabled
# new.exactly.once.support = enabled
```

Once these properties file has been prepared, place it on every Apache Kafka unit:

```bash
cat mm2.properties | juju ssh kafka-k8s/<id> sudo -i 'sudo tee -a /etc/kafka/mm2.properties'
```

where `<id>` is the id of the Charmed Apache Kafka K8s unit.

## Starting a dedicated MirrorMaker cluster

We strongly recommend running MirrorMaker services on the downstream (target) cluster to avoid service impact due to resource use. Now that the properties are set on each unit of the new cluster, the MirrorMaker services can be started with JMX metrics exporters.

Prepare the `KAFKA_OPTS` environment variable for running with an exporter:

```bash
# building KAFKA_OPTS env-var for running with an exporter
export KAFKA_OPTS = "-Djava.security.auth.login.config=/etc/kafka/zookeeper-jaas.cfg -javaagent:/opt/kafka/libs/jmx_prometheus_javaagent.jar=9099:/etc/kafka/jmx_kafka_connect.yaml"
```

Start MirrorMaker on each target Charmed Apache Kafka K8s unit:

```bash
juju ssh kafka-k8s/<id> sudo -i 'cd /opt/kafka/bin && KAFKA_OPTS=$KAFKA_OPTS ./connect-mirror-maker.sh /etc/kafka/mm2.properties'
```

## Monitoring and validating data replication

The migration process can be monitored using built-in Apache Kafka bin commands on the original cluster. In the Charmed Apache Kafka K8s, these bin commands are also mapped to snap commands on the units (e.g `charmed-kafka.get-offsets` or `charmed-kafka.topics`).

To monitor the current consumer offsets, run the following on the original/source cluster being migrated from:

```bash
watch "bin/kafka-consumer-groups.sh --describe --offsets --bootstrap-server $OLD_SERVERS --all-groups"
```

An example output of which may look similar to this:

```text
GROUP           TOPIC               PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG             CONSUMER-ID                                             HOST            CLIENT-ID
admin-group-1   NEW-TOPIC           0          95              95              0               kafka-python-2.0.2-a95b3f90-75e9-4a16-b63e-5e021b7344c5 /10.248.204.1   kafka-python-2.0.2
admin-group-1   NEW-TOPIC           3          98              98              0               kafka-python-2.0.2-a95b3f90-75e9-4a16-b63e-5e021b7344c5 /10.248.204.1   kafka-python-2.0.2
admin-group-1   NEW-TOPIC           1          82              82              0               kafka-python-2.0.2-a95b3f90-75e9-4a16-b63e-5e021b7344c5 /10.248.204.1   kafka-python-2.0.2
admin-group-1   NEW-TOPIC           2          89              90              1               kafka-python-2.0.2-a95b3f90-75e9-4a16-b63e-5e021b7344c5 /10.248.204.1   kafka-python-2.0.2
admin-group-1   NEW-TOPIC           4          103             104             1               kafka-python-2.0.2-a95b3f90-75e9-4a16-b63e-5e021b7344c5 /10.248.204.1   kafka-python-2.0.2
```

There is also a [range of different metrics](https://kafka.apache.org/39/operations/geo-replication-cross-cluster-data-mirroring/#monitoring-geo-replication) made available by MirrorMaker during the migration. To check the metrics, send a request to the `/metrics` endpoint:

```shell
curl 10.248.204.198:9099/metrics | grep records_count
```

## Switching client traffic

Once happy with data migration, stop all active consumer applications on the original/source cluster and redirect them to the new/target Charmed Apache Kafka K8s cluster, making sure to use the Charmed Apache Kafka K8s cluster server addresses and authentication. After doing so, they will re-join their original consumer groups at the last committed offset it had originally, and continue consuming as normal.

Finally, the producer client applications can be stopped, updated with the Charmed Apache Kafka K8s cluster server addresses and authentication, and restarted, with any newly produced messages being received by the migrated consumer client applications, completing the migration of both the data, and the client applications.

## Stopping MirrorMaker replication

Once confident in the successful completion of the data client migration, stop the running MirrorMaker processes on each unit of the Charmed Apache Kafka K8s cluster.
