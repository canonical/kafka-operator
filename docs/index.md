(index)=

```{note}
This is a **IAAS/VM** operator. To deploy on Kubernetes, see [Charmed Apache Kafka K8s operator](https://charmhub.io/kafka-k8s).
```

# Charmed Apache Kafka documentation

Charmed Apache Kafka is an open-source operator that makes it easier to manage Apache Kafka, with built-in support for enterprise features. 

Apache Kafka is a free, open-source software project by the Apache Software Foundation. Users can find out more at the [Apache Kafka project page](https://kafka.apache.org).

Charmed Apache Kafka is built on top of [Juju](https://juju.is/) and reliably simplifies the deployment, scaling, design, and management of [Apache Kafka](https://kafka.apache.org/) in production. Additionally, you can use the charm to manage your Apache Kafka clusters with automation capabilities. It also offers replication, TLS, password rotation, easy-to-use application integration, and monitoring.
Charmed Apache Kafka operates Apache Kafka on physical systems, Virtual Machines (VM), and a wide range of cloud and cloud-like environments, including AWS, Azure, OpenStack, and VMware. 

Charmed Apache Kafka is a solution designed and developed to help ops teams and 
administrators automate Apache Kafka operations from [Day 0 to Day 2](https://codilime.com/blog/day-0-day-1-day-2-the-software-lifecycle-in-the-cloud-age/), across multiple cloud environments and platforms.

Charmed Apache Kafka is developed and supported by [Canonical](https://canonical.com/), as part of its commitment to 
provide open-source, self-driving solutions, seamlessly integrated using the Operator Framework Juju. Please 
refer to [Charmhub](https://charmhub.io/), for more charmed operators that can be integrated by [Juju](https://juju.is/).

## In this documentation

| | |
|--|--|
|  [Tutorials](/tutorial/1-introduction)</br>  Get started - a hands-on introduction to using Charmed Apache Kafka operator for new users </br> |  [How-to guides](/how-to/manage-units) </br> Step-by-step guides covering key operations and common tasks |
| [Reference](/reference/file-system-paths) </br> Technical information - specifications, APIs, architecture | [Explanation](/explanation/security) </br> Concepts - discussion and clarification of key topics  |

## Project and community

Charmed Apache Kafka is a distribution of Apache Kafka. It’s an open-source project that welcomes community contributions, suggestions, fixes and constructive feedback.

- [Read our Code of Conduct](https://ubuntu.com/community/code-of-conduct)
- [Join the Discourse forum](https://discourse.charmhub.io/tag/kafka)
- [Contribute](https://github.com/canonical/kafka-operator/blob/main/CONTRIBUTING.md) and report [issues](https://github.com/canonical/kafka-operator/issues/new)
- Explore [Canonical Data Fabric solutions](https://canonical.com/data)
- [Contact us]([/t/13107) for all further questions

Apache®, Apache Kafka, Kafka®, and the Apache Kafka logo are either registered trademarks or trademarks of the Apache Software Foundation in the United States and/or other countries.

## License

The Charmed Apache Kafka Operator is free software, distributed under the Apache Software License, version 2.0. See [LICENSE](https://github.com/canonical/kafka-operator/blob/main/LICENSE) for more information.

# Navigation

[details=Navigation]

|Level | Path | Navlink|
|--- | --- | ---|
|1 | tutorial | [Tutorial]()|
|2 | t-overview | [1. Introduction](/tutorial/1-introduction)|
|2 | t-setup-environment | [2. Set up the environment](/tutorial/2-set-up-the-environment)|
|2 | t-deploy | [3. Deploy Apache Kafka](/tutorial/3-deploy-apache-kafka)|
|2 | t-relate-kafka | [4. Integrate with client applications](/tutorial/4-integrate-with-client-applications)|
|2 | t-manage-passwords | [5. Manage passwords](/tutorial/5-manage-passwords)|
|2 | t-enable-encryption | [6. Enable Encryption](/tutorial/6-enable-encryption)|
|2 | t-kafka-connect | [7. Use Kafka Connect for ETL]( /t/charmed-apache-kafka-documentation-tutorial-using-kafka-connect-for-etl/17862)|
|2 | t-reassign-partitions | [8. Rebalance and Reassign Partitions](/tutorial/8-rebalance-and-reassign-partitions)|
|2 | t-cleanup-environment | [9. Cleanup your environment](/tutorial/9-cleanup-your-environment)|
|1 | how-to | [How To]() |
|2 | h-deploy | [Deploy]() |
|3 | h-deploy-anywhere| [Deploy anywhere](/how-to/deploy/deploy-anywhere)|
|3 | h-deploy-aws | [Deploy on AWS](/how-to/deploy/deploy-on-aws)|
|3 | h-deploy-azure | [Deploy on Azure](/how-to/deploy/deploy-on-azure)|
|3 | h-kraft-mode | [KRaft mode](https://discourse.charmhub.io/t/15976)|
|2 | h-manage-units | [Manage units](/how-to/manage-units)|
|2 | h-manage-app | [Manage applications](/how-to/manage-applications)|
|2 | h-enable-encryption | [Enable encryption](/how-to/enable-encryption)|
|2 | h-upgrade | [Upgrade](/how-to/upgrade)|
|2 | h-monitoring | [Monitoring]()|
|3 | h-enable-monitoring | [Enable Monitoring](/how-to/monitoring/enable-monitoring)|
|3 | h-integrate-alerts-dashboards | [Integrate alerts and dashboards](/how-to/monitoring/integrate-alerts-and-dashboards)|
|2 | h-cluster-replication | [Cluster replication]()|
|3 | h-cluster-migration | [Migrate a cluster](/how-to/cluster-replication/migrate-a-cluster)|
|3 | h-cluster-replication | [Cluster replication](/how-to/cluster-replication/cluster-replication)|
|2 | h-create-mtls-client-credentials | [Create mTLS Client Credentials](/how-to/create-mtls-client-credentials)|
|2 | h-enable-oauth | [Enable Oauth through Hydra](/how-to/enable-oauth-through-hydra)|
|2 | h-backup | [Back up and restore](/how-to/back-up-and-restore)|
|2 | h-manage-message-schemas | [Manage message schemas](/how-to/manage-message-schemas)|
|2 | h-kafka-connect | [Use Kafka Connect for ETL workloads](/how-to/use-kafka-connect-for-etl-workloads)|
|1 | reference | [Reference]()|
|2 | r-releases | [Release Notes]()|
|3 | r-rev156_126 | [Revision 156/126](/)|python3 -m doh -i discourse.charmhub.io -t 10288 --generate_h1
|3 | r-rev156_136 | [Revision 156/136](/)|
|3 | r-rev195_149 | [Revision 195/149](/)|
|3 | r-rev205 | [Revision 205](/)|
|2 | r-actions | [Actions](https://charmhub.io/kafka/actions?channel=3/stable)|
|2 | r-configurations | [Configurations](https://charmhub.io/kafka/configure?channel=3/stable)|
|2 | r-libraries | [Libraries](https://charmhub.io/kafka/libraries/kafka_libs?channel=3/stable)|
|2 | r-file-system-paths | [File System Paths](/reference/file-system-paths)|
|2 | r-snap-entrypoints | [Snap Entrypoints](/reference/snap-entrypoints)|
|2 | r-listeners | [Apache Kafka Listeners](/reference/apache-kafka-listeners)|
|2 | r-statuses | [Statuses](/reference/statuses)|
|2 | r-requirements | [Requirements](/reference/requirements)|
|2 | r-performance-tuning | [Performance Tuning](/reference/performance-tuning)|
|2 | r-contacts | [Contact](/reference/contact)|
|1 | explanation | [Explanation]()|
|2 | e-security | [Security](/explanation/security)|
|2 | e-cryptography | [Cryptography](/explanation/cryptography)|
|2 | e-cluster-configuration | [Cluster configuration](/explanation/cluster-configuration)|
|2 | e-trademarks | [Trademarks](/explanation/trademarks)|
|2 | e-mirrormaker | [MirrorMaker2.0](/)|

[/details]

# Redirects

[details=Mapping table]
| Path | Location |
| ---- | -------- |
[/details]

-------------------------

abatisse | 2024-02-22 08:43:52 UTC | #2

Same issue with links as in [kafka-k8s](https://discourse.charmhub.io/t/charmed-kafka-k8s-documentation/10296/4?u=abatisse)

-------------------------


```{toctree}
:titlesonly:
:maxdepth: 2
:glob:
:hidden:

Home <self>
tutorial*/index
how*/index
reference*/index
explanation*/index
*
