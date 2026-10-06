The Charmed Apache Kafka K8s Operator delivers automated operations management from [Day 0 to Day 2](https://codilime.com/blog/day-0-day-1-day-2-the-software-lifecycle-in-the-cloud-age/) on the [Apache Kafka](https://kafka.apache.org/) event streaming platform. 
It is an open-source, end-to-end, production-ready data platform [on top of Juju](https://juju.is/). As a first step, this tutorial shows you how to get Charmed Apache Kafka K8s up and running, but the tutorial does not stop there. 
As currently Apache Kafka requires a paired [Apache ZooKeeper](https://zookeeper.apache.org/) deployment in production, this operator makes use of the [Apache ZooKeeper Operator](https://github.com/canonical/zookeeper-operator) for various essential functions.
Through this tutorial, you will learn a variety of operations, everything from adding replicas to advanced operations such as enabling Transcript Layer Security (TLS).

In this tutorial, we will walk through how to:

- Set up an environment using [Multipass](https://multipass.run/) with [MicroK8s](https://microk8s.io/) and [Juju](https://juju.is/).
- Deploy Charmed Apache Kafka K8s using a couple of commands.
- Get the admin credentials directly.
- Add high availability with replication.
- Change the admin password.
- Automatically create Apache Kafka users via Juju relations.
- Enable secure connection with TLS.

While this tutorial intends to guide and teach you as you deploy Charmed Apache Kafka K8s, it will be most beneficial if you already have a familiarity with:

- Basic terminal commands.
- Apache Kafka concepts such as replication and users.

## Minimum requirements

Before we start, make sure your machine meets the following requirements:

- Ubuntu 20.04 (Focal) or later.
- `8` GB of RAM.
- `2` CPU threads.
- At least `20` GB of available storage.
- Access to the internet for downloading the required snaps and charms.
