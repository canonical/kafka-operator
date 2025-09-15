(explanation-backups)=
# Backups

Apache Kafka is a distributed data streaming platform.
It is not designed to serve as a long-term data store.
Its architecture relies on replication and retention rather than traditional backups.
For this reason, you do not need to back up either data or metadata from an Apache Kafka cluster.

## Data

Apache Kafka topics are implemented as replicated logs.
Each partition has one or more replicas distributed across brokers.
If a broker fails, other replicas keep the data available.
This built-in replication ensures resilience.

Apache Kafka also applies retention policies, which automatically delete records
after a configurable time period or once a log size threshold is reached.
Because Apache Kafka is designed for streaming rather than archival storage,
durable data should be persisted in external systems such as databases,
data warehouses, or object storages.

## Metadata

In earlier versions of Apache Kafka (3.x and earlier),
cluster metadata was managed in Apache ZooKeeper.
Backing up Apache ZooKeeper was an important operational concern.

With Kafka 4.x, Apache Kafka uses
[KRaft mode](https://kafka.apache.org/documentation/#kraft),
where metadata is stored Kafka’s KRaft quorum.
This metadata is replicated and fault-tolerant by design.
As a result, there is no need to back up metadata separately or use Apache ZooKeeper.
