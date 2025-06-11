[note]
This is a **IAAS/VM** operator. To deploy on Kubernetes, see [Charmed Apache Kafka K8s operator](https://charmhub.io/kafka-k8s).
[/note]

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
|  [Tutorials](/t/charmed-kafka-tutorial-overview/10571)</br>  Get started - a hands-on introduction to using Charmed Apache Kafka operator for new users </br> |  [How-to guides](/t/charmed-kafka-how-to-manage-units/10287) </br> Step-by-step guides covering key operations and common tasks |
| [Reference](/t/charmed-apache-kafka-documentation-reference-file-system-paths/13262) </br> Technical information - specifications, APIs, architecture | [Explanation](/t/charmed-apache-kafka-documentation-explanation-security-hardening-guide/15830) </br> Concepts - discussion and clarification of key topics  |

## Project and community

Charmed Apache Kafka is a distribution of Apache Kafka. It’s an open-source project that welcomes community contributions, suggestions, fixes and constructive feedback.

- [Read our Code of Conduct](https://ubuntu.com/community/code-of-conduct)
- [Join the Discourse forum](https://discourse.charmhub.io/tag/kafka)
- [Contribute](https://github.com/canonical/kafka-operator/blob/main/CONTRIBUTING.md) and report [issues](https://github.com/canonical/kafka-operator/issues/new)
- Explore [Canonical Data Fabric solutions](https://canonical.com/data)
- [Contact us](/t/13107) for all further questions

Apache®, Apache Kafka, Kafka®, and the Apache Kafka logo are either registered trademarks or trademarks of the Apache Software Foundation in the United States and/or other countries.

## License

The Charmed Apache Kafka Operator is free software, distributed under the Apache Software License, version 2.0. See [LICENSE](https://github.com/canonical/kafka-operator/blob/main/LICENSE) for more information.

# Contents

1. [Tutorial](tutorial)
  1. [1. Introduction](tutorial/t-overview.md)
  1. [2. Set up the environment](tutorial/t-setup-environment.md)
  1. [3. Deploy Apache Kafka](tutorial/t-deploy.md)
  1. [4. Integrate with client applications](tutorial/t-relate-kafka.md)
  1. [5. Manage passwords](tutorial/t-manage-passwords.md)
  1. [6. Enable Encryption](tutorial/t-enable-encryption.md)
  1. [7. Use Kafka Connect for ETL](tutorial/t-kafka-connect.md)
  1. [8. Rebalance and Reassign Partitions](tutorial/t-reassign-partitions.md)
  1. [9. Cleanup your environment](tutorial/t-cleanup-environment.md)
1. [How To](how-to)
  1. [Deploy](how-to/h-deploy)
    1. [Deploy anywhere](how-to/h-deploy/h-deploy-anywhere.md)
    1. [Deploy on AWS](how-to/h-deploy/h-deploy-aws.md)
    1. [Deploy on Azure](how-to/h-deploy/h-deploy-azure.md)
    1. [KRaft mode](how-to/h-deploy/h-kraft-mode.md)
  1. [Manage units](how-to/h-manage-units.md)
  1. [Manage applications](how-to/h-manage-app.md)
  1. [Enable encryption](how-to/h-enable-encryption.md)
  1. [Upgrade](how-to/h-upgrade.md)
  1. [Monitoring](how-to/h-monitoring)
    1. [Enable Monitoring](how-to/h-monitoring/h-enable-monitoring.md)
    1. [Integrate alerts and dashboards](how-to/h-monitoring/h-integrate-alerts-dashboards.md)
  1. [Cluster replication](how-to/h-cluster-replication)
    1. [Migrate a cluster](how-to/h-cluster-replication/h-cluster-migration.md)
    1. [Cluster replication](how-to/h-cluster-replication/h-cluster-replication.md)
  1. [Create mTLS Client Credentials](how-to/h-create-mtls-client-credentials.md)
  1. [Enable Oauth through Hydra](how-to/h-enable-oauth.md)
  1. [Back up and restore](how-to/h-backup.md)
  1. [Manage message schemas](how-to/h-manage-message-schemas.md)
  1. [Use Kafka Connect for ETL workloads](how-to/h-kafka-connect.md)
1. [Reference](reference)
  1. [Release Notes](reference/r-releases)
    1. [Revision 156/126](reference/r-releases/r-rev156_126.md)
    1. [Revision 156/136](reference/r-releases/r-rev156_136.md)
    1. [Revision 195/149](reference/r-releases/r-rev195_149.md)
    1. [Revision 205](reference/r-releases/r-rev205.md)
  1. [File System Paths](reference/r-file-system-paths.md)
  1. [Snap Entrypoints](reference/r-snap-entrypoints.md)
  1. [Apache Kafka Listeners](reference/r-listeners.md)
  1. [Statuses](reference/r-statuses.md)
  1. [Requirements](reference/r-requirements.md)
  1. [Performance Tuning](reference/r-performance-tuning.md)
  1. [Contact](reference/r-contacts.md)
1. [Explanation](explanation)
  1. [Security](explanation/e-security.md)
  1. [Cryptography](explanation/e-cryptography.md)
  1. [Cluster configuration](explanation/e-cluster-configuration.md)
  1. [Trademarks](explanation/e-trademarks.md)
  1. [MirrorMaker2.0](explanation/e-mirrormaker.md)