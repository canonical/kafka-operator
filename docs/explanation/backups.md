---
myst:
  html_meta:
    description: "Apache Kafka backups explained - what replication does and does not protect against, and how to plan recovery for Charmed Apache Kafka."
---

(explanation-backups)=
# Backups

Apache Kafka is a distributed data streaming platform.
It is not designed to serve as a long-term data store.
Its architecture relies on replication and retention rather than traditional backups.

```{attention}
The Charmed Apache Kafka charm does not provide a built-in backup and restore
workflow. Replication is **not** a substitute for a backup: it protects
against some infrastructure failures, but it does not protect against
deleted topics, misconfigured applications, operator mistakes replicated
across the cluster, retention expiry, or the loss of the entire cluster.
Plan disaster recovery for your deployment accordingly.
```

## Data

Apache Kafka topics are implemented as replicated logs.
Each partition has one or more replicas distributed across brokers.
If a broker fails, other replicas keep the data available.
This built-in replication ensures resilience against **broker-level failures**.

Replication does not help when:

* records are deleted (deliberately or accidentally) — the deletion is
  replicated to all copies of the partition
* retention policies expire records — this is by design, as Apache Kafka is
  built for streaming rather than archival storage
* a whole cluster is lost (for example, a cloud region failure or the loss of
  all brokers at once)

Because Apache Kafka is designed for streaming rather than archival storage,
durable data should be persisted in external systems such as databases,
data warehouses, or object storages. For recovery scenarios beyond broker
failure, treat those external systems — or a separate Kafka cluster kept in
sync with [cross-cluster replication](how-to-cluster-migration) — as your
recovery mechanism.

## Metadata

In earlier versions of Apache Kafka (3.x and earlier),
cluster metadata was managed in Apache ZooKeeper.
Backing up Apache ZooKeeper was an important operational concern.

With Kafka 4.x, Apache Kafka uses
[KRaft mode](https://kafka.apache.org/41/operations/kraft/),
where metadata is stored by each controller in Kafka’s KRaft quorum.
This metadata is replicated and fault-tolerant by design, so a single
controller failure does not lose metadata. As with data, replication does not
protect against logical corruption or the loss of a majority of the quorum.
