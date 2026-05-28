---
myst:
  html_meta:
    description: "Complete documentation for Charmed Apache Kafka operator - deploy, manage, and scale Charmed Apache Kafka clusters on VMs, AWS, Azure, and OpenStack."
---

(index)=
# Charmed Apache Kafka documentation

Charmed Apache Kafka is an open-source operator, packaged as a
[Juju charm](https://documentation.ubuntu.com/juju/3.6/reference/charm/),
that simplifies the deployment, scaling, and management of
[Apache Kafka](https://kafka.apache.org) clusters on physical hardware, VMs,
and cloud environments including AWS, Azure, OpenStack, and VMware.

```{note}
This is an **IAAS/VM** charmed operator.
To deploy on Kubernetes, see [Charmed Apache Kafka K8s operator](https://documentation.ubuntu.com/charmed-kafka-k8s/4/).
```

The charm automates Apache Kafka operations from
[Day 0 to Day 2](https://codilime.com/blog/day-0-day-1-day-2-the-software-lifecycle-in-the-cloud-age/)
with capabilities such as replication, TLS encryption, password rotation,
application integration, and monitoring.

## In this documentation

### Get started

Set up your environment, understand the requirements, and deploy your first Charmed Apache Kafka cluster.

| | |
|---|---|
| **Getting started** | [Introduction](tutorial-introduction) • [Environment setup](tutorial-environment) • [Requirements](reference-requirements) |
| **Deployment** | [Deploy](how-to-deploy-index) • [Juju CLI](how-to-deploy-anywhere) • [Terraform](how-to-deploy-terraform) • [AWS](how-to-deploy-on-aws) • [Azure](how-to-deploy-on-azure) • [Juju Spaces](how-to-deploy-spaces) |

### Operate and maintain

Manage day-to-day cluster operations, keep it up to date, and ensure resilience through replication and upgrades.

| | |
|---|---|
| **Operations** | [Connections management](how-to-client-connections) • [Unit management](how-to-manage-units) • [Monitoring](how-to-monitoring) • [Listeners](reference-broker-listeners) • [Statuses](reference-statuses) |
| **Maintenance** | [Version upgrade](how-to-upgrade) • [Migration](how-to-cluster-migration) • [Replication](how-to-cluster-replication) • [MirrorMaker](explanation-mirrormaker2-0) • [Backups](explanation-backups) |

### Secure and extend

Protect your cluster with encryption and authentication, and integrate additional tools.

| | |
|---|---|
| **Security** | [Overview](explanation-security) • [Enable encryption](how-to-tls-encryption) • [mTLS](how-to-create-mtls-client-credentials) • [OAuth](how-to-enable-oauth) • [Cryptography](explanation-cryptography) |
| **Extensions** | [Kafka Connect](how-to-use-kafka-connect-for-etl-workloads) • [Schema registry](how-to-schemas-serialisation) • [Kafka UI](how-to-kafka-ui) |
| **Internals** | [Snap commands](reference-snap-commands) • [File paths](reference-file-system-paths) • [Performance tuning](reference-performance-tuning) • [Terraform module](reference-terraform) • [Release notes](reference-release-notes-index) |

## How the documentation is organised

This documentation uses the [Diátaxis documentation structure](https://diataxis.fr/):

- The [Tutorial](tutorial-introduction) walks you through deploying your first Charmed Apache Kafka cluster from scratch, step by step.
- [How-to guides](how-to-index) help you solve specific operational tasks such as enabling TLS, connecting clients, or scaling brokers.
- [Reference](reference-index) lets you look up configuration options, status codes, file paths, and system requirements.
- [Explanation](explanation-index) helps you understand the design decisions behind security, replication, and integration architecture.

## Project and community

Charmed Apache Kafka is part of the [Juju](https://juju.is/) ecosystem of open-source,
self-driving deployment tools. It can be integrated with multiple other Juju charms,
also available on [Charmhub](https://charmhub.io/).

It’s an open-source project developed and supported by [Canonical](https://canonical.com/)
that welcomes community contributions, suggestions, fixes and constructive feedback.

- [Read our Code of Conduct](https://ubuntu.com/community/code-of-conduct)
- [Join the Discourse forum](https://discourse.charmhub.io/tag/kafka)
- [Contribute](https://github.com/canonical/kafka-operator/blob/main/CONTRIBUTING.md) and report [issues](https://github.com/canonical/kafka-operator/issues/new)
- Explore [Canonical's open-source data platform](https://canonical.com/data)
- [Contact us](reference-contact) for all further questions

## License and trademarks

[Apache Kafka](https://kafka.apache.org) is a free, open-source software project
by the Apache Software Foundation.
Apache®, Apache Kafka, Kafka®, and the Apache Kafka logo are either registered trademarks
or trademarks of the Apache Software Foundation in the United States and/or other countries.

The Charmed Apache Kafka Operator is free software, distributed under the Apache Software License,
version 2.0.
See [LICENSE](https://github.com/canonical/kafka-operator/blob/main/LICENSE) for more information.

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
