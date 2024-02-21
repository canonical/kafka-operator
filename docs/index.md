## Charmed Kafka Documentation

The Charmed Kafka Operator delivers automated operations management from day 0 to day 2 on the [Apache Kafka](https://kafka.apache.org) event streaming platform. It is an open source, end-to-end, production ready data platform on top of cloud native technologies.

This operator charm comes with features such as:
- Fault-tolerance, replication, scalability and high-availability out-of-the-box.
- SASL/SCRAM auth for Broker-Broker and Client-Broker authentication enabled by default.
- Access control management supported with user-provided ACL lists.

The Kafka Operator uses the latest upstream Kafka binaries released by the The Apache Software Foundation that comes with Kafka, made available using the [`charmed-kafka` snap ](https://snapcraft.io/charmed-kafka) distributed by Canonical.

As currently Kafka requires a paired ZooKeeper deployment in production, this operator makes use of the [ZooKeeper Operator](https://github.com/canonical/zookeeper-operator) for various essential functions.

The Charmed Kafka operator comes in two flavours to deploy and operate Kafka on [physical/virtual machines](https://github.com/canonical/kafka-operator) and [Kubernetes](https://github.com/canonical/kafka-k8s-operator). Both offer features such as replication, TLS, password rotation, and easy to use integration with applications. The Charmed Kafka Operator meets the need of deploying Kafka in a structured and consistent manner while allowing the user flexibility in configuration. It simplifies deployment, scaling, configuration and management of Kafka in production at scale in a reliable way.

### License

The Charmed Kafka Operator is free software, distributed under the Apache Software License, version 2.0. See [LICENSE](https://github.com/canonical/kafka-operator/blob/main/LICENSE) for more information.

## Project and community

Charmed Kafka is an official distribution of Apache Kafka. It’s an open-source project that welcomes community contributions, suggestions, fixes and constructive feedback.
- [Read our Code of Conduct](https://ubuntu.com/community/code-of-conduct)
- [Join the Discourse forum](/tag/kafka)
- [Contribute](https://github.com/canonical/kafka-operator/blob/main/CONTRIBUTING.md) and report [issues](https://github.com/canonical/kafka-operator/issues/new)
- Explore [Canonical Data Fabric solutions](https://canonical.com/data)
- [Contacts us]([/t/13107) for all further questions

## In this documentation

| | |
|--|--|
|  [Tutorials](/t/charmed-kafka-tutorial-overview/10571)</br>  Get started - a hands-on introduction to using Charmed MySQL operator for new users </br> |  [How-to guides](/t/charmed-kafka-how-to-manage-units/10287) </br> Step-by-step guides covering key operations and common tasks |
| [Reference](https://charmhub.io/kafka/actions?channel=3/stable) </br> Technical information - specifications, APIs, architecture | [Explanation]() </br> Concepts - discussion and clarification of key topics  |
