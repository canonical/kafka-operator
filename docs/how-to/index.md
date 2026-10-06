(how-to-index)=
# How-to guides

The following guides cover key processes and common tasks for Charmed Apache Kafka K8s. If you are missing a particular how-to guide, feel free to leave us feedback via button above, or [contact](reference-contact) directly.

## Deployment

Deployment follows a broadly similar pattern on all platforms, but due to differences in the platforms, configuration and deployment must be approached differently in each case.

* Common [deployment guide](how-to-deploy-deploy-anywhere)
* Specific deployment guides:
  * [AKS](how-to-deploy-on-aks)
  * [EKS](how-to-deploy-on-eks)

## Management

For guidance on managing your deployed Charmed Apache Kafka K8s, see:

* [How to manage units](how-to-manage-units)
* [How to manage related applications](how-to-manage-applications)
* [How to upgrade](how-to-upgrade)

## Security

We have a series of How-to guides for security-related topics:

* [Enable encryption](how-to-enable-encryption)
* [Back up and restore](how-to-back-up-and-restore)

See also: our [security overview](explanation-security) page.

## Monitoring

Monitoring Charmed Apache Kafka K8s is typically done with the [Canonical Observability Stack](https://charmhub.io/topics/canonical-observability-stack).
See our How to set up monitoring guide for the following topics:

* [Enable monitoring](how-to-monitoring-enable-monitoring)
* [Add custom alerts and dashboards](how-to-monitoring-integrate-alerts-and-dashboards)

## Cluster replication and migration

Both migrating and replicating Apache Kafka cluster can be done with MirrorMaker 2.
See the guides for more details:

* [Cluster migration](how-to-cluster-replication-migrate-a-cluster)

## Advanced

Advanced features of Charmed Apache Kafka K8s include:

* [Message schemas management](how-to-manage-message-schemas)

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
Migrate a cluster<migrate.md>
external-k8s-connection.md
Back up and restore<back-up-and-restore.md>
Manage message schemas<schemas.md>
Create mTLS client credentials<create-mtls-client-credentials.md>
Troubleshoot<troubleshooting.md>
```
