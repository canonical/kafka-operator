(explanation-mirrormaker2-0)=
# MirrorMaker 2.0 overview

Under the hood, MirrorMaker uses Kafka Connect source connectors to replicate data. These include:

- **MirrorSourceConnector** - replicates topics from an original cluster to a new cluster. It also replicates ACLs and is necessary for the MirrorCheckpointConnector to run

- **MirrorCheckpointConnector** - periodically tracks offsets. If enabled, it also synchronises consumer group offsets between the original and new clusters

- **MirrorHeartbeatConnector** - periodically checks connectivity between the original and new clusters

Together, they are used for cluster -> cluster replication of topics, consumer groups, topic configuration and ACLs, while preserving partitioning and consumer offsets. For more detail on MirrorMaker internals, consult the [Apache Kafka documentation on replication](https://kafka.apache.org/39/operations/geo-replication-cross-cluster-data-mirroring/) and the [MirrorMaker 2.0 KIP](https://cwiki.apache.org/confluence/display/KAFKA/KIP-382%3A+MirrorMaker+2.0). In practice, it enables the one-way syncing of data between two Apache Kafka clusters with minimal impact on the ongoing production service.

MirrorMaker runs as a distributed service on the target cluster. It can consume all or a subset of topics, groups, and offsets from the source (called `active`) cluster and replicate them one-way to the target (`passive`) cluster, which may not yet be serving external clients.

In addition to the [MirrorMaker-specific configuration](https://kafka.apache.org/39/configuration/mirrormaker-configs/), the MirrorMaker service can also be configured using many of the same settings as [Kafka Connect](https://kafka.apache.org/39/configuration/kafka-connect-configs/).

## Charmed MirrorMaker integrator

The [MirrorMaker Integrator charm](https://charmhub.io/mirrormaker-connect-integrator) enables the management of Apache Kafka Connect tasks to mirror and replicate topics from one Charmed Apache Kafka K8s application to another.

The MirrorMaker application has two endpoints that can be used with a Kafka cluster: `source` and `target`. The `source` endpoint is used to integrate with the active cluster, while the `target` endpoint is used to integrate with the passive cluster.
