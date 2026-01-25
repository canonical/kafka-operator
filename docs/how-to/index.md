---
myst:
  html_meta:
    description: "Comprehensive how-to guides for Charmed Apache Kafka - deployment, management, security, monitoring, and cluster replication."
---

(how-to-index)=
# How-to guides

The following guides cover key processes and common tasks for Charmed Apache Kafka. If you are missing a particular how-to guide, feel free to leave us feedback via button above, or [contact](reference-contact) directly.

## Deployment

Deployment follows a broadly similar pattern on all platforms, but due to differences in the platforms, configuration and deployment must be approached differently in each case.

* Common [deployment guide](how-to-deploy-anywhere)
* Specific deployment guides:
  * [AWS](how-to-deploy-on-aws)
  * [Azure](how-to-deploy-on-azure)

## Management

For guidance on managing your deployed Charmed Apache Kafka, see:

* [How to manage units](how-to-manage-units)
* [How to manage client connections](how-to-client-connections)
* [How to upgrade](how-to-upgrade)

## Security

We have a series of How-to guides for security-related topics:

* [TLS encryption](how-to-tls-encryption)
* [Create mTLS credentials](how-to-create-mtls-client-credentials)

See also: our [security overview](explanation-security) page.

## Monitoring

Monitoring Charmed Apache Kafka is typically done with the [Canonical Observability Stack](https://charmhub.io/topics/canonical-observability-stack).
See our How to set up monitoring guide for the following topics:

* [Enable monitoring](how-to-monitoring-enable-monitoring)
* [Add custom alerts and dashboards](how-to-monitoring-integrate-alerts-and-dashboards)

## Cluster replication and migration

Both migrating and replicating Apache Kafka cluster can be done with MirrorMaker 2.
See the guides for more details:

* [Cluster migration](how-to-cluster-migration)
* [Replication](how-to-cluster-replication)

## Advanced

Advanced features of Charmed Apache Kafka include:

* [Schemas and serialisation](how-to-schemas-serialisation)
* [Kafka Connect usage](how-to-use-kafka-connect-for-etl-workloads)

```{toctree}
:titlesonly:
:maxdepth: 2
:hidden:

Deploy<deploy/index.md>
Manage units<manage-units.md>
Client connections<client-connections.md>
Encryption<tls-encryption.md>
Upgrades<upgrade.md>
Monitoring<monitoring.md>
cluster/index.md
Create mTLS credentials<create-mtls-client-credentials.md>
Schemas and serialisation<schemas-serialisation.md>
Kafka Connect<kafka-connect.md>
```
