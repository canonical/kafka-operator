# Tutorial
<!-- # Charmed Apache Kafka tutorial -->

The Charmed Apache Kafka Operator delivers automated operations management from [Day 0 to Day 2](https://codilime.com/blog/day-0-day-1-day-2-the-software-lifecycle-in-the-cloud-age/) on the [Apache Kafka](https://kafka.apache.org/) event streaming platform.
It is an open source, end-to-end, production-ready data platform [on top of Juju](https://juju.is/). As a first step this tutorial shows you how to get Charmed Apache Kafka up and running, but the tutorial does not stop there.
Through this tutorial, you will learn a variety of operations, everything from adding replicas to advanced operations such as enabling SSL encryption, cross-cluster asynchronous replication and more.

In this tutorial, we will walk through how to:

- Set up your local environment using LXD and Juju.
- Deploy Charmed Apache Kafka using only a few commands.
- Get the admin credentials directly.
- Add high-availability with replication.
- Change the admin password.
- Automatically create Apache Kafka users via Juju relations.
- Use Cruise Control for cluster rebalancing.
- Use Karapace for schema management and message serialisation.
- Use Apache Kafka Connect for moving data between data applications.

While this tutorial intends to guide and teach you as you deploy Charmed Apache Kafka, it will be most beneficial if you already have a familiarity with:

- Basic Unix shell commands.
- General data-intensive application concepts such as partitioning, replication and user management.

## Minimum requirements

Before we start, make sure your machine meets the following requirements:

- Ubuntu 24.04 (Noble) or later.
- `8` GB of RAM.
- `2` CPU cores.
- At least `20` GB of available storage.
- Access to the internet for downloading the required snaps and charms.
