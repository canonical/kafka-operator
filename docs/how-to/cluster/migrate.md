(how-to-cluster-migration)=
# Migrate from a non-charmed Kafka clusters

This How-To guide covers executing a cluster migration from an existing Kafka cluster, to a Charmed Apache Kafka deployment using MirrorMaker 2.0.

The MirrorMaker tasks run on a distributed Charmed Apache Kafka Connect cluster of workers. These tasks act as consumer clients reading data from an existing cluster (source), and as producer clients writing data to the Charmed Apache Kafka cluster (target). Data and consumer offsets for specified topics will be synced **one-way** in parallel (one process on each unit) until both clusters are in-sync, with all data replicated across both in real-time.

```{note}
For a brief explanation of how MirrorMaker works, see the [MirrorMaker explanation](explanation-mirrormaker2-0) page.
```

## Pre-requisites

To migrate a cluster we need:

- An "old" existing Kafka cluster to migrate from.
  - The cluster needs to be reachable from/to the new Charmed Apache Kafka Connect cluster. 
- A bootstrapped Juju VM cloud
- A Charmed Apache Kafka Connect cluster to run the MirrorMaker tasks. For guidance on how to deploy a new Charmed Apache Kafka Connect cluster, see:
    - The [How-to use Kafka Connect for ETL workloads guide](how-to-use-kafka-connect-for-etl-workloads)
- A Charmed Apache Kafka to migrate data to. For guidance on how to deploy a new Charmed Apache Kafka, see:
  - The [Charmed Apache Kafka Tutorial](tutorial-introduction)
  - The [How to deploy guide](how-to-deploy-deploy-anywhere) for Charmed Apache Kafka
- The CLI tool `yq` - [GitHub repository](https://github.com/mikefarah/yq)
  - `snap install yq --channel=v3/stable`

## Get new charm cluster endpoints and credentials

By design, the Charmed Apache Kafka will not expose any available connections until related to by a client. In this guide, we will deploy a `data-integrator` application and integrate it to a `kafka` application, requesting `admin` level privileges:

```bash
juju deploy data-integrator --channel=edge -n 1 --config extra-user-roles="admin" --config topic-name="__data-integrator-user"
juju integrate kafka data-integrator
```

When the `data-integrator` charm relates to a `kafka` application on the `kafka_client` relation interface, passing `extra-user-roles=admin`, a new user with `super.user` permissions will be created on that cluster, with the charm passing back the credentials and broker addresses in the relation data to the `data-integrator`.

Charmed Apache Kafka Connect also needs to be related to the `kafka` application to be granted permissions and endpoints to connect to Charmed Apache Kafka:

```bash
juju integrate kafka-connect kafka
```

As we will need full access to both Kafka clusters, we will use credentials provided to the `data-integrator`. Get the SASL credentials to connect to the target Charmed Apache Kafka cluster:

```bash
SECRET=juju show-unit data-integrator/0 --format yaml | yq -r '.. | ."secret-user"? // empty' | grep -oP "[^\/]*$"
export NEW_USERNAME=$(juju show-secret --reveal $SECRET | yq -r '.. | .username? // empty')
export NEW_PASSWORD=$(juju show-secret --reveal $SECRET | yq -r '.. | .password? // empty')
```

Get the comma-delimited list of bootstrap-server IPs:

```bash
export NEW_SERVERS=$(juju show-unit data-integrator/0 | yq -r '.. | .endpoints? // empty')
```

Building full `sasl.jaas.config` for authorisation:

```bash
export NEW_SASL_JAAS_CONFIG="org.apache.kafka.common.security.scram.ScramLoginModule required username=\""${NEW_USERNAME}"\" password=\""${NEW_PASSWORD}\"\;
```

## Get old cluster endpoints and credentials

MirrorMaker needs full `super.user` permissions on **BOTH** clusters. It supports every possible `security.protocol` supported by Apache Kafka. In this guide, we will make the assumption that the source cluster is using `SASL_PLAINTEXT` authentication, as such, the required information is as follows:

- `OLD_SERVERS` -- comma-separated list of Apache Kafka server IPs and ports to connect to
- `NEW_SASL_JAAS_CONFIG` -- string of `sasl.jaas.config` property

```{note}
For `SSL` or `SASL_SSL` authentication, see the configuration options supported by Kafka Connect in the [Apache Kafka documentation](https://kafka.apache.org/documentation/#connectconfigs).
```

## Run MirrorMaker cross-cluster replication task

First, get the `admin` credentials for the Charmed Apache Kafka Connect application:

```bash
CONNECT_SECRET_KEY=$(juju list-secrets | grep kafka-connect | awk '{ print $1}')
export CONNECT_USERNAME=admin
export CONNECT_PASSWORD=$(juju show-secret --reveal $CONNECT_SECRET_KEY --format yaml | yq '.. | ."admin-password"? // empty' | tr -d '"')
export CONNECT_ENDPOINTS=$(juju show-unit kafka-connect/0 --format json | yq '.. | ."public-address"? // empty' | tr -d '"')
```

To start the MirrorMaker replication task, make an HTTP request to Charmed Apache Kafka Connect, using the credentials and endpoints for both Kafka clusters:

<details>

<summary>Example HTTP request to Kafka Connect</summary>

```bash
curl -u $CONNECT_USERNAME:$CONNECT_PASSWORD \
    -H "Content-Type: application/json" \
    -X POST http://$CONNECT_ENDPOINTS:8083/connectors \
    -d '{
        "name": "mirrormaker-migration",
        "config": {
            "connector.class": "org.apache.kafka.connect.mirror.MirrorSourceConnector",
            "replication.factor": "-1",
            "target.cluster.sasl.jaas.config": "$OLD_SASL_JAAS_CONFIG",
            "sync.topic.acls.enabled": "true",
            "tasks.max": "1",
            "replication.policy.class": "org.apache.kafka.connect.mirror.IdentityReplicationPolicy",
            "source.cluster.alias": "old",
            "refresh.groups.enabled": "true",
            "config.providers": "file",
            "producer.override.security.protocol": "SASL_PLAINTEXT",
            "sync.topic.configs.interval.seconds": "5",
            "consumer.auto.offset.reset": "earliest",
            "target.cluster.security.protocol": "SASL_PLAINTEXT",
            "config.providers.file.class": "org.apache.kafka.common.config.provider.FileConfigProvider",
            "replication.policy.separator": ".replica.",
            "value.converter": "org.apache.kafka.connect.converters.ByteArrayConverter",
            "key.converter": "org.apache.kafka.connect.converters.ByteArrayConverter",
            "clusters": "old-kafka,new-kafka",
            "refresh.groups.interval.seconds": "5",
            "refresh.topics.interval.seconds": "5",
            "topics.exclude": ".*[-.]internal,.*replica.*,__.*,connect-.*,new-kafka.*",
            "offset-syncs.topic.replication.factor": "-1",
            "producer.override.bootstrap.servers": "$NEW_SERVERS",
            "topics": ".*",
            "offset-syncs.topic.location": "target",
            "refresh.topics.enabled": "true",
            "target.cluster.sasl.mechanism": "SCRAM-SHA-512",
            "producer.enable.idempotence": "true",
            "groups": ".*",
            "source.cluster.sasl.jaas.config": "$OLD_SASL_JAAS_CONFIG",
            "source.cluster.bootstrap.servers": "$OLD_SERVERS",
            "source.cluster.sasl.mechanism": "SCRAM-SHA-512",
            "target.cluster.alias": "new",
            "groups.exclude": "console-consumer-.*, connect-.*, __.*",
            "name": "mirror_source_mirrormaker_r19",
            "target.cluster.bootstrap.servers": "$NEW_SERVERS",
            "producer.override.sasl.jaas.config": "$NEW_SASL_JAAS_CONFIG",
            "producer.override.sasl.mechanism": "SCRAM-SHA-512",
            "sync.topic.configs.enabled": "true",
            "source.cluster.security.protocol": "SASL_PLAINTEXT"
        }'
```

</details>

## Monitoring and validating data replication

The migration process can be monitored using the original cluster's built-in Apache Kafka bin commands. In the Charmed Apache Kafka cluster, these bin commands are also mapped to snap commands on the units (e.g. `charmed-kafka.get-offsets` or `charmed-kafka.topics`).

To monitor the current consumer offsets, run the following on the source Kafka cluster being migrated from:

```bash
watch "bin/kafka-consumer-groups.sh --describe --offsets --bootstrap-server $OLD_SERVERS --all-groups"
```

An example output of which may look similar to this:

```text
GROUP                TOPIC           PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG        CONSUMER-ID
mm2-connect-cluster  source.topic.A  0          1500            1500            0          connector-consumer-MirrorSourceConnector-0-abc...
mm2-connect-cluster  source.topic.A  1          1498            1499            1          connector-consumer-MirrorSourceConnector-0-abc...
mm2-connect-cluster  source.topic.A  2          1505            1505            0          connector-consumer-MirrorSourceConnector-1-def...
mm2-connect-cluster  source.topic.B  0          875             875             0          connector-consumer-MirrorSourceConnector-1-def...
```

To monitor the produced data flowing in to the target Charmed Apache Kafka cluster, you can query the Prometheus metrics collected - see [How to set up monitoring](how-to-set-up-monitoring) for more information.
