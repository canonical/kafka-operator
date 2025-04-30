## MirrorMaker2 overview

Under the hood, MirrorMaker uses Kafka Connect source connectors to replicate data, those being the following:

- **MirrorSourceConnector** - replicates topics from an original cluster to a new cluster. It also replicates ACLs and is necessary for the MirrorCheckpointConnector to run
- **MirrorCheckpointConnector** - periodically tracks offsets. If enabled, it also synchronizes consumer group offsets between the original and new clusters
- **MirrorHeartbeatConnector** - periodically checks connectivity between the original and new clusters

Together, they are used for cluster->cluster replication of topics, consumer groups, topic configuration and ACLs, preserving partitioning and consumer offsets. For more detail on MirrorMaker internals, consult the [MirrorMaker README.md](https://github.com/apache/kafka/blob/trunk/connect/mirror/README.md) and the [MirrorMaker 2.0 KIP](https://cwiki.apache.org/confluence/display/KAFKA/KIP-382%3A+MirrorMaker+2.0). In practice, it lets sync data one way between two live Apache Kafka clusters with minimal impact on the ongoing production service.

In short, MirrorMaker runs as a distributed service on the new cluster, and consumes all topics, groups and offsets from the still-active original cluster in production, before producing them one-way to the new cluster that may not yet be serving traffic to external clients. The original, in-production cluster is referred to as an ‘active’ cluster, and the new cluster still waiting to serve external clients is ‘passive’. The MirrorMaker service can be configured using much the same configuration as available for Kafka Connect.