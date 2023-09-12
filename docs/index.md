## Charmed Kafka Documentation

The Charmed Kafka Operator delivers automated operations management from day 0 to day 2 on the [Apache Kafka](https://kafka.apache.org) event streaming platform. It is an open source, end-to-end, production ready data platform on top of cloud native technologies.

This operator charm comes with features such as:
- Fault-tolerance, replication, scalability and high-availability out-of-the-box.
- SASL/SCRAM auth for Broker-Broker and Client-Broker authenticaion enabled by default.
- Access control management supported with user-provided ACL lists.

The Kafka Operator uses the latest upstream Kafka binaries released by the The Apache Software Foundation that comes with Kafka, made available using the [`charmed-kafka` snap ](https://snapcraft.io/charmed-kafka) distributed by Canonical.

As currently Kafka requires a paired ZooKeeper deployment in production, this operator makes use of the [ZooKeeper Operator](https://github.com/canonical/zookeeper-operator) for various essential functions.

The Charmed Kafka operator comes in two flavours to deploy and operate Kafka on [physical/virtual machines](https://github.com/canonical/kafka-operator) and [Kubernetes](https://github.com/canonical/kafka-k8s-operator). Both offer features such as replication, TLS, password rotation, and easy to use integration with applications. The Charmed Kafka Operator meets the need of deploying Kafka in a structured and consistent manner while allowing the user flexibility in configuration. It simplifies deployment, scaling, configuration and management of Kafka in production at scale in a reliable way.

## Charm version, environment and OS

A charm version is a combination of both the application version and / (slash) the channel, e.g. 3/stable, 3/candidate, 3/edge. The channels are ordered from the most stable to the least stable, candidate, and edge. More risky channels like edge are always implicitly available. So, if the candidate is listed, you can pull the candidate and edge. When stable is listed, all three are available. 

You can deploy the charm a stand-alone machine or cloud and cloud-like environments, including AWS, Azure, OpenStack and VMWare.

The upper portion of this page describes the Operating System (OS) where the charm can run e.g. 3/stable is compatible and should run in a machine with Ubuntu 22.04 OS.


## Security, Bugs and feature request

If you find a bug in this snap or want to request a specific feature, here are the useful links:

* Raise issues or feature requests in [Github](https://github.com/canonical/kafka-operator/issues)

* Security issues in the Charmed Kafka Operator can be reported through [LaunchPad](https://wiki.ubuntu.com/DebuggingSecurity#How%20to%20File). Please do not file GitHub issues about security issues.

* Meet the community and chat with us if there are issues and feature requests in our [Mattermost Channel](https://chat.charmhub.io/charmhub/channels/data-platform)

## Contributing

Please see the [Juju SDK docs](https://juju.is/docs/sdk) for guidelines on enhancements to this charm following best practice guidelines, and [CONTRIBUTING.md](https://github.com/canonical/kafka-operator/blob/main/CONTRIBUTING.md) for developer guidance.

## License

The Charmed Kafka Operator is free software, distributed under the Apache Software License, version 2.0. See [LICENSE](https://github.com/canonical/kafka-operator/blob/main/LICENSE) for more information.
