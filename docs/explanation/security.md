(explanation-security)=
# Security

This document provides an overview of security features and guidance for hardening the security of [Charmed Apache Kafka K8s](https://charmhub.io/kafka-k8s) deployments, including setting up and managing a secure environment.

## Environment

The environment where Charmed Apache Kafka K8s operate can be divided into two components:

1. Kubernetes
2. Juju

### Kubernetes

Charmed Apache Kafka K8s can be deployed on top of several Kubernetes distributions. 
The following table provides references for the security documentation for the 
main supported cloud platforms.

| Cloud              | Security guides                                                                                                                                                                                                                                                                                                                                   |
|--------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Charmed Kubernetes | [Security in Charmed Kubernetes](https://ubuntu.com/kubernetes/docs/security)                                                                                                                                                                                                                                                                    |
| AWS EKS            | [Best Practices for Security, Identity and Compliance](https://aws.amazon.com/architecture/security-identity-compliance), [AWS security credentials](https://docs.aws.amazon.com/IAM/latest/UserGuide/security-creds.html), [Security in EKS](https://docs.aws.amazon.com/eks/latest/userguide/security.html) | 
| Azure              | [Azure security best practices and patterns](https://learn.microsoft.com/en-us/azure/security/fundamentals/best-practices-and-patterns), [Managed identities for Azure resource](https://learn.microsoft.com/en-us/entra/identity/managed-identities-azure-resources/), [Security in AKS](https://learn.microsoft.com/en-us/azure/aks/concepts-security)                                                      |

### Juju

Juju is the component responsible for orchestrating the entire lifecycle, from deployment to Day 2 operations. For more information on Juju security hardening, see the
[Juju security page](https://documentation.ubuntu.com/juju/3.6/explanation/juju-security/) and the [How to harden your deployment](https://documentation.ubuntu.com/juju/latest/howto/manage-your-juju-deployment/harden-your-juju-deployment/) guide.

#### Cloud credentials

When configuring cloud credentials to be used with Juju, ensure that users have the correct permissions to operate at the required level on the Kubernetes cluster.
Juju superusers responsible for bootstrapping and managing controllers require elevated permissions to manage several kinds of resources. For this reason, the
K8s user for bootstrapping and managing the deployments should have full permissions, such as:

* create, delete, patch, and list:
  * namespaces
  * services
  * deployments
  * statefulsets
  * pods
  * PVCs

In general, it is common practice to run Juju using the admin role of K8s, to have full permissions on the Kubernetes cluster. 

#### Juju users

It is very important that Juju users are set up with minimal permissions depending on the scope of their operations. 
Please refer to the [User access levels](https://juju.is/docs/juju/user-permissions) documentation for more information on the access levels and corresponding abilities.

Juju user credentials must be stored securely and rotated regularly to limit the chances of unauthorised access due to credentials leakage.

## Applications

In the following, we provide guidance on how to harden your deployment using:

1. Base images
2. Charmed operator security upgrades
3. Encryption 
4. Authentication
5. Monitoring and auditing

### Base images

Charmed Apache Kafka K8s and Charmed Apache ZooKeeper K8s run on top of Rockcraft-based images shipping the Apache Kafka and Apache ZooKeeper 
distribution binaries built by Canonical, and available in the [Apache Kafka release page](https://launchpad.net/kafka-releases) and 
[Apache ZooKeeper release page](https://launchpad.net/zookeeper-releases), respectively. Both images are based on Ubuntu 22.04. 

The images that can be found in the [Charmed Apache Kafka rock](https://github.com/canonical/charmed-spark-rock) and 
[Charmed Apache ZooKeeper rock](https://github.com/canonical/charmed-zookeeper-rock) Github repositories are used as the base 
images for the different pods providing Apache Kafka and Apache ZooKeeper services. 
The following table summarises the relation between the component and its underlying base image. 

| Component         | Image                                                                                                 |
|-------------------|-------------------------------------------------------------------------------------------------------|
| Charmed Apache Kafka     | [`charmed-kafka`](https://github.com/orgs/canonical/packages/container/package/charmed-kafka)         |
| Charmed Apache ZooKeeper | [`charmed-zookeeper`](https://github.com/orgs/canonical/packages/container/package/charmed-zookeeper) |

New versions of Charmed Apache Kafka and Charmed Apache ZooKeeper images may be released to provide patching of vulnerabilities (CVE).

### Charmed operator security upgrades

Charmed Apache Kafka K8s and Charmed Apache ZooKeeper K8s operators install a pinned revision of the images outlined in the previous table
to provide reproducible and secure environments.
New versions of Charmed Apache Kafka K8s and Charmed Apache ZooKeeper K8s operators may therefore be released to provide patching of vulnerabilities (CVE).
It is important to refresh the charm regularly to make sure the workload is as secure as possible.
For more information on how to refresh the charm, see the [how-to refresh](how-to-upgrade) user guide.

### Encryption

Charmed Apache Kafka K8s must be deployed with encryption enabled.
To do that, you need to integrate Charmed Apache Kafka K8s and Charmed Apache ZooKeeper K8s charms with one of the TLS certificate operator charms.
Please refer to the [Charming Security page](https://charmhub.io/topics/security-with-x-509-certificates) for more information on how to select the right certificate
provider for your use case.

For more information on encryption, see the [Cryptography](explanation-cryptography) explanation page and [How to enable encryption](how-to-enable-encryption) guide.

### Authentication

Charmed Apache Kafka K8s supports the following authentication layers:

1. [SCRAM-based SASL Authentication](how-to-manage-applications)
2. [certificate-base Authentication (mTLS)](how-to-manage-applications)
3. OAuth Authentication using [Hydra](https://discourse.charmhub.io/t/how-to-connect-to-kafka-using-hydra-as-oidc-provider/14610) or [Google](https://discourse.charmhub.io/t/how-to-connect-to-kafka-using-google-as-oidc-provider/14611)

Each combination of authentication scheme and encryption is associated with the dedicated listener and it maps to a well-defined port.
See the [listener reference documentation](reference-broker-listeners) for more information.

### Monitoring and auditing

Charmed Apache Kafka K8s provides native integration with the [Canonical Observability Stack (COS)](https://charmhub.io/topics/canonical-observability-stack).
To reduce the blast radius of infrastructure disruptions, the general recommendation is to deploy COS and the observed application into separate environments, isolated from one another. Refer to the [COS production deployments best practices](https://charmhub.io/topics/canonical-observability-stack/reference/best-practices) for more information.

For instructions, see the [How to integrate the Charmed Apache Kafka K8s deployment with COS](how-to-monitoring-enable-monitoring) and [How to customise the alerting rules and dashboards](how-to-monitoring-integrate-alerts-and-dashboards) guides.

External user access to Apache Kafka is logged to the `kafka-authorizer.log` that is pushed to [Loki endpoint](https://charmhub.io/loki-k8s) and exposed via [Grafana](https://charmhub.io/grafana), both components being part of the COS stack.

Access denials are logged at the `INFO` level, whereas allowed accesses are logged at the `DEBUG` level. Depending on the auditing needs,
customise the logging level either for all logs via the [`log_level`](https://charmhub.io/kafka-k8s/configurations?channel=3/stable#log_level) configuration option or
only tune the logging level of the `authorizerAppender` in the `log4j.properties` file. See the [file system paths](reference-file-system-paths) for further information.

## Additional Resources

For details on the cryptography used by Charmed Apache Kafka K8s, see the [Cryptography](explanation-cryptography) explanation page.
