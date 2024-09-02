# Cluster migration using MirrorMaker2.0

This How-To guide covers executing a cluster migration to a Charmed Kafka deployment using MirrorMaker2.0, running as a process on each of the Juju units in an active/passive setup, where MirrorMaker will act as a consumer from an existing cluster, and a producer to the Charmed Kafka cluster. In parallel (one process on each unit), data and consumer offsets for all existing topics will be synced one-way until both clusters are in-sync, with all data replicated across both in real-time.

## MirrorMaker2 overview

Under the hood, MirrorMaker uses Kafka Connect source connectors to replicate data, those being the following:
- **MirrorSourceConnector** - replicates topics from an original cluster to a new cluster. It also replicates ACLs and is necessary for the MirrorCheckpointConnector to run
- **MirrorCheckpointConnector** - periodically tracks offsets. If enabled, it also synchronizes consumer group offsets between the original and new clusters
- **MirrorHeartbeatConnector** - periodically checks connectivity between the original and new clusters

Together, they are used for cluster->cluster replication of topics, consumer groups, topic configuration and ACLs, preserving partitioning and consumer offsets. For more detail on MirrorMaker internals, consult the [MirrorMaker README.md](https://github.com/apache/kafka/blob/trunk/connect/mirror/README.md) and the [MirrorMaker 2.0 KIP](https://cwiki.apache.org/confluence/display/KAFKA/KIP-382%3A+MirrorMaker+2.0). In practice, it lets sync data one-way between two live Kafka clusters with minimal impact on the ongoing production service.

In short, MirrorMaker runs as a distributed service on the new cluster, and consumes all topics, groups and offsets from the still-active original cluster in production, before producing them one-way to the new cluster that may not yet be serving traffic to external clients. The original, in-production cluster is referred to as an ‘active’ cluster, and the new cluster still waiting to serve external clients is ‘passive’. The MirrorMaker service can be configured using much the same configuration as available for Kafka Connect.

## Pre-requisites

- An existing Kafka cluster to migrate from
- A bootstrapped Juju VM machine cloud running Charmed Kafka to migrate to
    - A tutorial on how to set-up a Charmed Kafka deployment can be found as part of the [Charmed Kafka Tutorial](/t/charmed-kafka-tutorial-overview/10571)
    - The CLI tool `yq` - https://github.com/mikefarah/yq
    - `snap install yq --channel=v3/stable`

## Getting Charmed Kafka cluster details and admin credentials

By design, the `kafka` charm will not expose any available connections until related to by a client. In this case, we deploy `data-integrator` charms and relating them to each `kafka` application, requesting `admin` level privileges:

```bash
juju deploy data-integrator --channel=edge -n 1 --config extra-user-roles="admin" --config topic-name="default"
juju relate kafka data-integrator
```

When the `data-integrator` charm relates to a `kafka` application on the `kafka-client` relation interface, passing `extra-user-roles=admin`, a new user with `super.user` permissions will be created on that cluster, with the charm passing back the credentials and broker addresses in the relation data to the `data-integrator`.
As we will need full access to both clusters, we must grab these newly-generated authorisation credentials from the `data-integrator`:

```bash
# SASL credentials to connect to the Charmed Kafka cluster
export NEW_USERNAME=$(juju show-unit data-integrator/0 | yq -r '.. | .username? // empty')
export NEW_PASSWORD=$(juju show-unit data-integrator/0 | yq -r '.. | .password? // empty')

# list of bootstrap-server IPs
export NEW_SERVERS=$(juju show-unit data-integrator/0 | yq -r '.. | .endpoints? // empty')

# building full sasl.jaas.config for authorisation
export NEW_SASL_JAAS_CONFIG="org.apache.kafka.common.security.scram.ScramLoginModule required username=\""${NEW_USERNAME}"\" password=\""${NEW_PASSWORD}\"\;
```

## Required source cluster credentials

To authenticate MirrorMaker to both clusters, it will need full `super.user` permissions on **BOTH** clusters. MirrorMaker supports every possible `security.protocol` supported by Apache Kafka. In this guide, we will make the assumption that the original cluster is using `SASL_PLAINTEXT` authentication, as such, the required information is as follows:

```bash
# comma-separated list of kafka server IPs and ports to connect to
OLD_SERVERS

# string of sasl.jaas.config property
OLD_SASL_JAAS_CONFIG
```

> **NOTE** - If using `SSL` or `SASL_SSL` authentication, review the configuration options supported by Kafka Connect in the [Apache Kafka documentation](https://kafka.apache.org/documentation/#connectconfigs)

## Generating `mm2.properties` file on the Charmed Kafka cluster

MirrorMaker takes a `.properties` file for its configuration to fine-tune behaviour. See below an example `mm2.properties` file that can be placed on each of the Charmed Kafka units using the above credentials:

```bash
# Aliases for each cluster, can be set to any unique alias
clusters = old,new 

# Specifies that data from 'old' should be consumed and produced to 'new', and NOT visa-versa, i.e 'active/passive' setup
old->new.enabled = true
new->old.enabled = false

# comma-separated list of kafka server IPs and ports to connect from both clusters
old.bootstrap.servers=$OLD_SERVERS
new.bootstrap.servers=$NEW_SERVERS

# sasl authentication config for each cluster, in this case using the 'admin' users created by the integrator charm for Charmed Kafka
old.sasl.jaas.config=$OLD_SASL_JAAS_CONFIG
new.sasl.jaas.config=$NEW_SASL_JAAS_CONFIG

# if not deployed with TLS, Charmed Kafka uses SCRAM-SHA-512 for SASL auth, with a SASL_PLAINTEXT listener
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
# NOTE - EOD support guarantees released with Kafka 3.5.0 so some of these options may not work as expected
old.producer.enable.idempotence=true
new.producer.enable.idempotence=true
old.producer.acks=all
new.producer.acks=all
# old.exactly.once.support = enabled
# new.exactly.once.support = enabled
```

Once these properties have been generated (in this example, saved to `/tmp/mm2.properties`), it is needed to place them on every Charmed Kafka unit:

```bash
cat /tmp/mm2.properties | juju ssh kafka/<id> sudo -i 'sudo tee -a /var/snap/charmed-kafka/current/etc/kafka/mm2.properties'
```

## Starting a dedicated MirrorMaker cluster

It is strongly advised to run MirrorMaker services on the downstream cluster to avoid service impact due to resource use. Now that the properties are set on each unit of the new cluster, the MirrorMaker services can be started using with JMX metrics exporters using the following:

```bash
# building KAFKA_OPTS env-var for running with an exporter
export KAFKA_OPTS = "-Djava.security.auth.login.config=/var/snap/charmed-kafka/current/etc/kafka/zookeeper-jaas.cfg -javaagent:/var/snap/charmed-kafka/current/opt/kafka/libs/jmx_prometheus_javaagent.jar=9099:/var/snap/charmed-kafka/current/etc/kafka/jmx_kafka_connect.yaml"

# To start MM on kafka/<id> unit
juju ssh kafka/<id> sudo -i 'cd /snap/charmed-kafka/current/opt/kafka/bin && KAFKA_OPTS=$KAFKA_OPTS ./connect-mirror-maker.sh /var/snap/charmed-kafka/current/etc/kafka/mm2.properties'
```

## Monitoring and validating data replication

The migration process can be monitored using built-in Kafka bin-commands on the original cluster. In the Charmed Kafka cluster, these bin-commands are also mapped to snap commands on the units (e.g `charmed-kafka.get-offsets` or `charmed-kafka.topics`).

To monitor the current consumer offsets, run the following on the original cluster being migrated from:

```bash
watch "bin/kafka-consumer-groups.sh --describe --offsets --bootstrap-server $OLD_SERVERS --all-groups
```

An example output of which may look similar to this:

```
GROUP           TOPIC               PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG             CONSUMER-ID                                             HOST            CLIENT-ID
admin-group-1   NEW-TOPIC           0          95              95              0               kafka-python-2.0.2-a95b3f90-75e9-4a16-b63e-5e021b7344c5 /10.248.204.1   kafka-python-2.0.2
admin-group-1   NEW-TOPIC           3          98              98              0               kafka-python-2.0.2-a95b3f90-75e9-4a16-b63e-5e021b7344c5 /10.248.204.1   kafka-python-2.0.2
admin-group-1   NEW-TOPIC           1          82              82              0               kafka-python-2.0.2-a95b3f90-75e9-4a16-b63e-5e021b7344c5 /10.248.204.1   kafka-python-2.0.2
admin-group-1   NEW-TOPIC           2          89              90              1               kafka-python-2.0.2-a95b3f90-75e9-4a16-b63e-5e021b7344c5 /10.248.204.1   kafka-python-2.0.2
admin-group-1   NEW-TOPIC           4          103             104             1               kafka-python-2.0.2-a95b3f90-75e9-4a16-b63e-5e021b7344c5 /10.248.204.1   kafka-python-2.0.2
```

There is also a [range of different metrics](https://github.com/apache/kafka/blob/trunk/connect/mirror/README.md#monitoring-an-mm2-process) made available by MirrorMaker during the migration. These can be accessed with something similar to:

```
curl 10.248.204.198:9099/metrics | grep records_count
```

## Switching client traffic from original cluster to Charmed Kafka cluster

Once happy that all the necessary data has been successfully migrated, stop all active consumer applications on the original cluster, and redirect them to the Charmed Kafka cluster, making sure to use the Charmed Kafka cluster server addresses and authentication. After doing so, they will re-join their original consumer groups at the last committed offset it had originally, and continue consuming as normal.
Finally, the producer client applications can be stopped, updated with the Charmed Kafka cluster server addresses and authentication, and restarted, with any newly produced messages being received by the migrated consumer client applications, completing the migration of both the data, and the client applications.

## Stopping MirrorMaker replication

Once confident in the successful completion of the data client migration, the running processes on each of the charm units can be killed, stopping the MirrorMaker processes active on the Charmed Kafka cluster.