# Charmed Apache Kafka tutorial

The Charmed Apache Kafka Operator delivers automated operations management from [Day 0 to Day 2](https://codilime.com/blog/day-0-day-1-day-2-the-software-lifecycle-in-the-cloud-age/) on the [Apache Kafka](https://kafka.apache.org/) event streaming platform. 
It is an open source, end-to-end, production-ready data platform [on top of Juju](https://juju.is/). As a first step this tutorial shows you how to get Charmed Apache Kafka up and running, but the tutorial does not stop there. 
As currently Apache Kafka requires a paired [Apache ZooKeeper](https://zookeeper.apache.org/) deployment in production, this operator makes use of the [Charmed Apache ZooKeeper Operator](https://github.com/canonical/zookeeper-operator) for various essential functions.
Through this tutorial, you will learn a variety of operations, everything from adding replicas to advanced operations such as enabling Transport Layer Security (TLS). 

In this tutorial, we will walk through how to:

- Set up your environment using LXD and Juju.
- Deploy Charmed Apache Kafka using a couple of commands.
- Get the admin credentials directly.
- Add high availability with replication.
- Change the admin password.
- Automatically create Apache Kafka users via Juju relations. 

While this tutorial intends to guide and teach you as you deploy Charmed Apache Kafka, it will be most beneficial if you already have a familiarity with: 
- Basic terminal commands.
- Apache Kafka concepts such as replication and users.

## Minimum requirements

Before we start, make sure your machine meets the following requirements:

* Ubuntu 20.04 (Focal) or later.
* `8` GB of RAM.
* `2` CPU threads.
* At least `20` GB of available storage.
* Access to the internet for downloading the required snaps and charms.

## Step-by-step guide

Here’s an overview of the steps required with links to our separate tutorials that deal with each individual step:
* [Set up the environment](/t/charmed-kafka-tutorial-setup-environment/10575)
* [Deploy Charmed Apache Kafka](/t/charmed-kafka-tutorial-deploy-kafka/10567)
* [Integrate with client applications](/t/charmed-kafka-tutorial-relate-kafka/10573)
* [Manage passwords](/t/charmed-kafka-tutorial-manage-passwords/10569)
* [Enable encryption](/t/charmed-kafka-documentation-tutorial-enable-security/12043)
* [Cleanup your environment](/t/charmed-kafka-tutorial-cleanup-environment/10565)