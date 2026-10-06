(index)=

```{note}
This is a **Kubernetes** operator. To deploy on IAAS/VM, see [Charmed Apache Kafka operator](https://documentation.ubuntu.com/charmed-kafka/3/).
```

# Charmed Apache Kafka K8s documentation

Charmed Apache Kafka K8s is an open-source software operator, packaged as a [Juju charm](https://documentation.ubuntu.com/juju/3.6/reference/charm/), that simplifies the deployment, scaling, and management of Apache Kafka clusters on Kubernetes for both on-premise installation (e.g., using MicroK8s) or cloud services (e.g., AWS, EKS).

[Apache Kafka](https://kafka.apache.org) is a free, open-source software project by the Apache Software Foundation.

The charm helps ops teams and administrators automate Apache Kafka operations from [Day 0 to Day 2](https://codilime.com/blog/day-0-day-1-day-2-the-software-lifecycle-in-the-cloud-age/) with additional capabilities, such as: replication, TLS encryption, password rotation, easy-to-use application integration, and monitoring.

## In this documentation

| | |
|--|--|
| **Tutorial** | [Introduction](tutorial-introduction) • [Step 1: Environment setup](tutorial-environment) |
| **Deployment** | [Main deployment guide](how-to-deploy-deploy-anywhere) • [AKS](how-to-deploy-on-aks) • [EKS](how-to-deploy-on-eks) • [Apache ZooKeeper configuration](explanation-cluster-configuration) • [Requirements](reference-requirements) |
| **Operations** | [Application management](how-to-manage-applications) • [Unit management](how-to-manage-units) • [Monitoring](how-to-monitoring) • [File system paths](reference-file-system-paths) • [Broker listeners](reference-broker-listeners) • [Status reference](reference-statuses) • [External K8s connection](how-to-external-k8s-connection) • [Troubleshooting](troubleshooting) |
| **Maintenance** | [Version upgrade](how-to-upgrade) • [Migration](how-to-cluster-replication-migrate-a-cluster) • [MirrorMaker](explanation-mirrormaker2-0) • [Backups](how-to-back-up-and-restore) |
| **Security** | [Overview](explanation-security) • [Enable encryption](how-to-enable-encryption) • [mTLS](how-to-create-mtls-client-credentials) • [Cryptography](explanation-cryptography) |
| **Extensions** | [Schema registry](how-to-manage-message-schemas) |

## How the documentation is organised

[Tutorial](tutorial-introduction): For new users needing to learn how to use Charmed Apache Kafka <br>
[How-to guides](how-to-index): For users needing step-by-step instructions to achieve a practical goal <br>
[Reference](reference-index): For precise, theoretical, factual information to be used while working with the charm <br>
[Explanation](explanation-index): For deeper understanding of key Charmed Apache Kafka concepts <br>

## Project and community

Charmed Apache Kafka K8s is part of the [Juju](https://juju.is/) ecosystem of open-source, self-driving deployment tools. It can be integrated with multiple other Juju charms, also available on [Charmhub](https://charmhub.io/).

It’s an open-source project developed and supported by [Canonical](https://canonical.com/) that welcomes community contributions, suggestions, fixes and constructive feedback.

- [Read our Code of Conduct](https://ubuntu.com/community/code-of-conduct)
- [Join the Discourse forum](https://discourse.charmhub.io/tag/kafka)
- [Contribute](https://github.com/canonical/kafka-k8s-operator/blob/main/CONTRIBUTING.md) and report [issues](https://github.com/canonical/kafka-k8s-operator/issues/new)
- Explore [Canonical Data Fabric solutions](https://canonical.com/data)
- [Contact us](reference-contact) for all further questions

## License and trademarks

Apache®, Apache Kafka, Kafka®, and the Apache Kafka logo are either registered trademarks or trademarks of the Apache Software Foundation in the United States and/or other countries.

The Charmed Apache Kafka Operator is free software, distributed under the Apache Software License, version 2.0. See [LICENSE](https://github.com/canonical/kafka-k8s-operator/blob/main/LICENSE) for more information.

```{toctree}
:titlesonly:
:maxdepth: 2
:hidden:

Home <self>
tutorial/index
how-to/index
reference/index
explanation/index
```
