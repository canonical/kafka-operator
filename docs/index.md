(index)=

```{note}
This is an **IAAS/VM** charmed operator. To deploy on Kubernetes, see [Charmed Apache Kafka K8s operator](https://charmhub.io/kafka-k8s).
```

# Charmed Apache Kafka documentation

Charmed Apache Kafka is an open-source software operator, packaged as a [Juju charm](https://documentation.ubuntu.com/juju/3.6/reference/charm/), that simplifies the deployment, scaling, and management of Apache Kafka clusters on physical hardware, Virtual Machines, as well as cloud and cloud-like environments including AWS, Azure, OpenStack, and VMware.

[Apache Kafka](https://kafka.apache.org) is a free, open-source software project by the Apache Software Foundation.

The charm helps ops teams and administrators automate Apache Kafka operations from [Day 0 to Day 2](https://codilime.com/blog/day-0-day-1-day-2-the-software-lifecycle-in-the-cloud-age/) with additional capabilities, such as: replication, TLS encryption, password rotation, easy-to-use application integration, and monitoring.

## In this documentation

| | |
|--|--|
|  [Tutorial](tutorial-introduction)</br>  Learn how to deploy, configure, and use the charm with our step-by-step guidance. Get started from [step one](tutorial-environment). </br> |  [How-to guides](how-to-index) </br> Practical instructions for key tasks, like [deploy](how-to-deploy-index) on different platforms, [manage](how-to-manage-units) Juju units, [Monitor](how-to-monitoring-enable-monitoring) metrics, [back up and restore](how-to-back-up-and-restore), use [Kafka Connect](how-to-use-kafka-connect-for-etl-workloads). |
| [Reference](reference-index) </br> Technical information, for example: charm's [actions](https://charmhub.io/kafka/actions?channel=3/edge), [configuration parameters](https://charmhub.io/kafka/configure?channel=3/edge), [libraries](https://charmhub.io/kafka/libraries/kafka_libs?channel=3/edge), [statuses](reference-statuses), as well as [requirements](reference-requirements), and [file system paths](reference-file-system-paths). | [Explanation](explanation-index) </br> Explore and grow your understanding of key topics, such as: [security](explanation-security) and [cryptography](explanation-cryptography), [Apache ZooKeeper](explanation-cluster-configuration) and [MirrorMaker](explanation-mirrormaker2-0) usage. |

## Project and community

Charmed Apache Kafka is part of the [Juju](https://juju.is/) ecosystem of open-source, self-driving deployment tools. It can be integrated with multiple other Juju charms, also available on [Charmhub](https://charmhub.io/).

It’s an open-source project developed and supported by [Canonical](https://canonical.com/) that welcomes community contributions, suggestions, fixes and constructive feedback.

- [Read our Code of Conduct](https://ubuntu.com/community/code-of-conduct)
- [Join the Discourse forum](https://discourse.charmhub.io/tag/kafka)
- [Contribute](https://github.com/canonical/kafka-operator/blob/main/CONTRIBUTING.md) and report [issues](https://github.com/canonical/kafka-operator/issues/new)
- Explore [Canonical Data Fabric solutions](https://canonical.com/data)
- [Contact us](https://discourse.charmhub.io/t/13107) for all further questions

## License and trademarks

Apache®, Apache Kafka, Kafka®, and the Apache Kafka logo are either registered trademarks or trademarks of the Apache Software Foundation in the United States and/or other countries.

The Charmed Apache Kafka Operator is free software, distributed under the Apache Software License, version 2.0. See [LICENSE](https://github.com/canonical/kafka-operator/blob/main/LICENSE) for more information.

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
