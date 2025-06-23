(how-to-index)=
# How-to guides

The following guides cover key processes and common tasks for Charmed Apache Kafka. If you are missing a particular how-to guide, feel free to leave us feedback via button above, or [contact](reference-contact) directly.

## Deployment

Deployment follows a broadly similar pattern on all platforms, but due to differences in the platforms, configuration and deployment must be approached differently in each case.

* Common [deployment guide](how-to-deploy-deploy-anywhere)
* Specific deployment guides:
  * [AWS](how-to-deploy-deploy-on-aws)
  * [Azure](how-to-deploy-deploy-on-azure)
  * [KRaft mode](how-to-deploy-kraft-mode)

## Management

For guidance on managing your deployed Charmed Apache Kafka, see:

* [How to manage units](how-to-manage-units)
* [How to manage related applications](how-to-manage-applications)
* [How to upgrade](how-to-upgrade)

## Security

We have a series of How-to guides for security-related topics:

* [Enable encryption](how-to-enable-encryption)
* [Create mTLS credentials](how-to-create-mtls-client-credentials)
* [Enable OAuth](how-to-enable-oauth-through-hydra)
* [Back up and restore](how-to-back-up-and-restore)

See also: our [security overview](explanation-security) page.

## Monitoring

Monitoring Charmed Apache Kafka is typically done with the [Canonical Observability Stack](https://charmhub.io/topics/canonical-observability-stack).
See our How to set up monitoring guide for the following topics:

* [Enable monitoring](how-to-monitoring-enable-monitoring)
* [Add custom alerts and dashboards](how-to-monitoring-integrate-alerts-and-dashboards)

## Cluster replication and migration

Both migrating and replicating Apache Kafka cluster can be done with MirrorMaker 2.
See the guides for more details:

* [Cluster migration](how-to-cluster-replication-migrate-a-cluster)
* [Replication](how-to-cluster-replication-cluster-replication)

## Advanced

Advanced features of Charmed Apache Kafka include:

* [Message schemas management](how-to-manage-message-schemas)
* [Kafka Connect usage](how-to-use-kafka-connect-for-etl-workloads)

<!-- Alternative landing page prototype
| | |
|--|--|
| **Deployment** </br> Deployment follows a broadly similar pattern on all platforms, but due to differences in the platforms, configuration and deployment must be approached differently in each case. </br> [Common deployment guide](how-to-deploy-deploy-anywhere), [AWS](how-to-deploy-deploy-on-aws), [Azure](how-to-deploy-deploy-on-azure), [KRaft mode](how-to-deploy-kraft-mode) |**Management** </br> For guidance on managing your deployed Charmed Apache Kafka, see: [How to manage units](how-to-manage-units), [How to manage related applications](how-to-manage-applications), [How to Upgrade](how-to-upgrade) | -->

```{toctree}
:titlesonly:
:maxdepth: 2
:hidden:

Deploy<deploy/index.md>
Manage units<manage-units.md>
Manage applications<manage-applications.md>
Encryption<enable-encryption.md>
Upgrade<upgrade.md>
Monitoring<monitoring.md>
cluster/index.md
Create mTLS client credentials<create-mtls-client-credentials.md>
Enable OAuth<oauth.md>
Back up and restore<back-up-and-restore.md>
Manage message schemas<schemas.md>
Use Kafka Connect<kafka-connect.md>
```
