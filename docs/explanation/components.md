---
myst:
  html_meta:
    description: "Overview of Charmed Apache Kafka components - brokers, KRaft controllers, Cruise Control, Kafka Connect, integrator charms, Karapace, Kafka UI, Data Integrator, and Terraform modules."
---

(explanation-components)=
# Components

Charmed Apache Kafka is more than a single charm: it is a family of operators, workload artefacts, and Terraform modules that together provide a fully managed Apache Kafka platform on both machines and Kubernetes. This page gives an overview of every component in that family, so you can tell at a glance what exists, what it does, and where to find it.

All charms are available individually on [Charmhub](https://charmhub.io/) and can also be deployed together with minimal configuration overhead via the [Charmed Apache Kafka Terraform bundle](https://github.com/canonical/kafka-bundle/tree/main/terraform).

## Core components

The core of the platform is a single charm, [`kafka`](https://charmhub.io/kafka) (and its Kubernetes counterpart [`kafka-k8s`](https://charmhub.io/kafka-k8s)), that can take on three different roles through its `roles` configuration option:

- `broker`: standard Apache Kafka broker functionality
- `controller`: KRaft (Kafka Raft) metadata quorum node
- `balancer`: Cruise Control node for partition rebalancing

This means the KRaft controller and the Cruise Control balancer are **not separate charms** — they are deployments of the same charm with a different `roles` value. For example, a split deployment runs brokers and controllers as separate applications of `kafka`, connected through the `peer-cluster-orchestrator` integration. For more detail, see the `roles` option in the [configurations reference](reference-configurations) and the [unit management guide](how-to-manage-units).

| Component | VM charm | K8s charm | Workload | Role |
|---|---|---|---|---|
| Apache Kafka broker | [`kafka`](https://charmhub.io/kafka) | [`kafka-k8s`](https://charmhub.io/kafka-k8s) | [charmed-kafka snap](https://snapcraft.io/charmed-kafka) / [OCI image](https://ghcr.io/canonical/charmed-kafka) | Runs the message brokers that store and serve data |
| KRaft controller | `kafka` (`roles=controller`) | `kafka-k8s` (`roles=controller`) | same | Manages cluster metadata through the Kafka Raft quorum |
| Cruise Control balancer | `kafka` (`roles=balancer`) | `kafka-k8s` (`roles=balancer`) | same | Monitors the cluster and rebalances partitions |

The source code for all four Kafka charms (machine and K8s, broker and Connect) lives in a single repository, [canonical/kafka-operator](https://github.com/canonical/kafka-operator). The former separate repositories ([`kafka-k8s-operator`](https://github.com/canonical/kafka-k8s-operator), [`kafka-connect-operator`](https://github.com/canonical/kafka-connect-operator), and [`kafka-connect-k8s-operator`](https://github.com/canonical/kafka-connect-k8s-operator)) have been archived and are now read-only.

### Cruise Control

[Cruise Control](https://github.com/linkedin/cruise-control) is LinkedIn's open-source system for streamlining the operation of large Kafka clusters. It continuously monitors cluster health and computes optimisation proposals for partition and replica placement, which can then be applied to rebalance the cluster.

In Charmed Apache Kafka, Cruise Control is bundled inside the `charmed-kafka` snap (as `charmed-kafka.cruise-control`) and enabled by deploying the charm with `roles=balancer`. For a step-by-step introduction, see the [partition rebalancing tutorial](tutorial-rebalance-partitions) and the [partition reassignment guide](how-to-manage-units).

## Kafka Connect

[Kafka Connect](https://kafka.apache.org/documentation/) is a framework for streaming data between Apache Kafka and external systems. It runs as a cluster of workers with a REST API (port 8083), and moves data through *connector plugins* that are supplied at deploy time via the `connect-plugin` resource.

| Component | VM charm | K8s charm | Workload |
|---|---|---|---|
| Kafka Connect | [`kafka-connect`](https://charmhub.io/kafka-connect) | [`kafka-connect-k8s`](https://charmhub.io/kafka-connect-k8s) | [charmed-kafka snap](https://snapcraft.io/charmed-kafka) / [OCI image](https://ghcr.io/canonical/charmed-kafka) |

For instructions on deploying and using Kafka Connect through the API, see the [Kafka Connect guide](how-to-use-kafka-connect-for-etl-workloads).

### Connect integrators

Connect integrator charms are lightweight operators that package a specific connector plugin and integrate it with a Kafka Connect cluster, so you don't have to build and attach plugin resources yourself. They are all built from the same template repository, [canonical/template-connect-integrator](https://github.com/canonical/template-connect-integrator).

| Integrator | VM charm | K8s charm | Direction | Connector plugin |
|---|---|---|---|---|
| MySQL | [`mysql-connect-integrator`](https://charmhub.io/mysql-connect-integrator) | [`mysql-connect-k8s-integrator`](https://charmhub.io/mysql-connect-k8s-integrator) | Source and sink | [Aiven JDBC connector](https://github.com/aiven/jdbc-connector-for-apache-kafka) |
| PostgreSQL | [`postgresql-connect-integrator`](https://charmhub.io/postgresql-connect-integrator) | [`postgresql-connect-k8s-integrator`](https://charmhub.io/postgresql-connect-k8s-integrator) | Source and sink | [Aiven JDBC connector](https://github.com/aiven/jdbc-connector-for-apache-kafka) |
| MongoDB | [`mongodb-connect-integrator`](https://charmhub.io/mongodb-connect-integrator) | [`mongodb-connect-k8s-integrator`](https://charmhub.io/mongodb-connect-k8s-integrator) | Source and sink | [Debezium MongoDB connector](https://github.com/debezium/debezium) |
| OpenSearch | [`opensearch-connect-integrator`](https://charmhub.io/opensearch-connect-integrator) | — | Sink | [Aiven OpenSearch connector](https://github.com/aiven/opensearch-connector-for-apache-kafka) |
| S3 | [`s3-connect-integrator`](https://charmhub.io/s3-connect-integrator) | [`s3-connect-k8s-integrator`](https://charmhub.io/s3-connect-k8s-integrator) | Sink | [Aiven S3 sink connector](https://github.com/aiven/s3-connector-for-apache-kafka) |
| MirrorMaker 2.0 | [`mirrormaker-connect-integrator`](https://charmhub.io/mirrormaker-connect-integrator) | [`mirrormaker-connect-k8s-integrator`](https://charmhub.io/mirrormaker-connect-k8s-integrator) | Replication | Built into Apache Kafka |

```{note}
The Connect integrator charms are currently published to the `edge` risk level only, and are not yet covered by the stable revision compatibility guarantees described in the [Compatibility](explanation-components-compatibility) section below. The OpenSearch integrator is available for machines only.
```

MirrorMaker 2.0 is a special case: it is not a source or sink connector but a replication mechanism built on Kafka Connect, used to migrate and replicate data between Kafka clusters. For how it works, see the [MirrorMaker explanation](explanation-mirrormaker2-0), and for usage, the [cluster migration](how-to-cluster-migration) and [cluster replication](how-to-cluster-replication) guides.

## Schema registry

[Karapace](https://www.karapace.io/) is an open-source schema registry, originally developed by Aiven as a drop-in replacement for the Confluent Schema Registry. It stores and version-controls schemas for message serialisation, so producers and consumers can evolve their data formats safely.

| Component | VM charm | K8s charm | Workload |
|---|---|---|---|
| Karapace | [`karapace`](https://charmhub.io/karapace) | [`karapace-k8s`](https://charmhub.io/karapace-k8s) | [charmed-karapace snap](https://snapcraft.io/charmed-karapace) |

Source code: [canonical/karapace-operator](https://github.com/canonical/karapace-operator) and [canonical/karapace-k8s-operator](https://github.com/canonical/karapace-k8s-operator). For managing schemas with Karapace, see the [schemas and serialisation guide](how-to-schemas-serialisation).

## Cluster administration UI

[Kafbat Kafka UI](https://github.com/kafbat/kafka-ui) is an open-source web interface for browsing and administering Kafka clusters: topics, messages, consumer groups, brokers, and ACLs. It integrates with Charmed Apache Kafka, Charmed Apache Kafka Connect, and Charmed Karapace.

| Component | VM charm | K8s charm | Workload |
|---|---|---|---|
| Kafka UI | [`kafka-ui`](https://charmhub.io/kafka-ui) | [`kafka-ui-k8s`](https://charmhub.io/kafka-ui-k8s) | [charmed-kafka-ui snap](https://snapcraft.io/charmed-kafka-ui) |

Source code: [canonical/kafka-ui-operator](https://github.com/canonical/kafka-ui-operator). For usage, see the [Kafka UI guide](how-to-kafka-ui).

## Client integration

The [Data Integrator](https://charmhub.io/data-integrator) charm ([source](https://github.com/canonical/data-integrator)) is a workload-less operator that requests Kafka credentials and endpoints from a Charmed Apache Kafka cluster through the `kafka_client` integration, and exposes them to external (non-Juju) client applications via its `get-credentials` action. It is also used to enable client listeners on an otherwise idle cluster. For details, see the [client connections guide](how-to-client-connections).

## Terraform modules

The [Charmed Apache Kafka Terraform bundle](https://github.com/canonical/kafka-bundle/tree/main/terraform) deploys the whole component family with minimal configuration overhead. It is composed of one module per charm, each sourced from the charm's own repository:

| Module | Source | Charm |
|---|---|---|
| `broker` | [kafka-operator](https://github.com/canonical/kafka-operator/tree/main/machine/terraform) | `kafka` |
| `controller` | [kafka-operator](https://github.com/canonical/kafka-operator/tree/main/machine/terraform) | `kafka` (`roles=controller`) |
| `connect` | [kafka-operator](https://github.com/canonical/kafka-operator/tree/main/connect_machine/terraform) | `kafka-connect` |
| `karapace` | [karapace-operator](https://github.com/canonical/karapace-operator/tree/main/terraform) | `karapace` |
| `ui` | [kafka-ui-operator](https://github.com/canonical/kafka-ui-operator/tree/main/terraform) | `kafka-ui` |

The Data Integrator is deployed by the bundle as a plain `juju_application` resource rather than a module. For the full input and output reference of the bundle, see the [Terraform module reference](reference-terraform) and the [Terraform deployment guide](how-to-deploy-terraform).

## How the components relate

The following diagram shows how the components connect to each other in a full deployment:

```{mermaid}
flowchart TB
    subgraph kafka-model["Kafka Juju model"]
        direction TB

        broker["<b>kafka</b><br>roles=broker"]
        kraft["<b>kafka</b><br>roles=controller"]
        balancer["<b>kafka</b><br>roles=balancer"]

        subgraph connect["<b>kafka-connect</b>"]
            direction LR
            workers["<b>Connect workers</b>"]
            integrators["<b>Connect integrators</b><br>mysql · postgresql · mongodb<br>opensearch · s3 · mirrormaker"]
        end

        karapace["<b>karapace</b>"]
        ui["<b>kafka-ui</b>"]
    end

    subgraph clients[" "]
        direction LR
        client["<b>Client applications</b><br>producers · consumers"]
        di["<b>data-integrator</b>"]
    end

    broker -->|"kafka_client"| client
    broker -->|"kafka_client"| di
    kraft <-->|"peer_cluster"| broker
    balancer <-->|"peer_cluster"| broker
    workers <-->|"kafka_client"| broker
    integrators -->|"connect_client"| workers
    karapace <-->|"kafka_client"| broker
    ui -->|"kafka_client"| broker
    ui -->|"karapace_client"| karapace
    ui -->|"connect_client"| workers
```

(explanation-components-compatibility)=
## Compatibility

The components above are released together per Apache Kafka major track (for example, `4/stable`), so a deployment should use components from the same track: a `4/stable` Kafka charm with a `4/stable` Kafka Connect charm, and so on.

The authoritative per-revision compatibility matrix — charm revisions, hardware architectures, Juju versions, and workload artefacts — is maintained in the [release notes](reference-release-notes-index) for each stable revision. The Connect integrator charms are published to `edge` only and are not covered by that matrix. For Juju versions, hardware requirements, and supported architectures, see the [system requirements](reference-requirements).
