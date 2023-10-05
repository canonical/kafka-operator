# Charmed Kafka tutorial

The Charmed Kafka Operator delivers automated operations management from [day 0 to day 2](https://codilime.com/blog/day-0-day-1-day-2-the-software-lifecycle-in-the-cloud-age/) on the [Apache Kafka](https://kafka.apache.org/) event streaming platform. 
It is an open source, end-to-end, production-ready data platform [on top of Juju](https://juju.is/). As a first step this tutorial shows you how to get Charmed Kafka up and running, but the tutorial does not stop there. 
As currently Kafka requires a paired [ZooKeeper](https://zookeeper.apache.org/) deployment in production, this operator makes use of the [ZooKeeper Operator](https://github.com/canonical/zookeeper-operator) for various essential functions.
Through this tutorial you will learn a variety of operations, everything from adding replicas to advanced operations such as enabling Transcript Layer Security (TLS). 

In this tutorial we will walk through how to:
- Set up your environment using LXD and Juju.
- Deploy Kafka using a couple of commands.
- Get the admin credentials directly.
- Add high availability with replication.
- Change the admin password.
- Automatically create Kafka users via Juju relations. 

While this tutorial intends to guide and teach you as you deploy Charmed Kafka, it will be most beneficial if you already have a familiarity with: 
- Basic terminal commands.
- Kafka concepts such as replication and users.

## Step-by-step guide

Here’s an overview of the steps required with links to our separate tutorials that deal with each individual step:
* [Set up the environment](/t/charmed-kafka-tutorial-setup-environment/10575)
* [Deploy Kafka](/t/charmed-kafka-tutorial-deploy-kafka/10567)
* [Manage passwords](/t/charmed-kafka-tutorial-manage-passwords/10569)
* [Relate your Kafka to other applications](/t/charmed-kafka-tutorial-relate-kafka/10573)
* [Enable encryption](/t/charmed-kafka-documentation-tutorial-enable-security/12043)
* [Cleanup your environment](/t/charmed-kafka-tutorial-cleanup-environment/10565)