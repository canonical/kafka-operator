---
myst:
  html_meta:
    description: "Security overview for Charmed Apache Kafka deployments - environment hardening, Juju security, cloud credentials, and authentication."
---

(explanation-security)=
# Security

This document provides an overview of security features and guidance for hardening
[Charmed Apache Kafka for VM](https://charmhub.io/kafka) and
[Charmed Apache Kafka K8s](https://charmhub.io/kafka-k8s) deployments.

## Environment

The environment where Charmed Apache Kafka operates can be divided into two components:

1. Cloud or Kubernetes substrate
2. Juju

### Cloud or Kubernetes substrate

Charmed Apache Kafka can be deployed on clouds, virtualisation layers, and
Kubernetes distributions:

| Substrate | Security guides |
|---|---|
| OpenStack | [OpenStack Security Guide](https://docs.openstack.org/security-guide/) |
| AWS | [Best Practices for Security, Identity and Compliance](https://aws.amazon.com/architecture/security-identity-compliance), [AWS security credentials](https://docs.aws.amazon.com/IAM/latest/UserGuide/security-creds.html), [Security in EKS](https://docs.aws.amazon.com/eks/latest/userguide/security.html) |
| Azure | [Azure security best practices and patterns](https://learn.microsoft.com/en-us/azure/security/fundamentals/best-practices-and-patterns), [Managed identities for Azure resources](https://learn.microsoft.com/en-us/entra/identity/managed-identities-azure-resources/), [Security in AKS](https://learn.microsoft.com/en-us/azure/aks/concepts-security) |
| Charmed Kubernetes | [Security in Charmed Kubernetes](https://ubuntu.com/kubernetes/docs/security) |

### Juju

Juju is the component responsible for orchestrating the entire lifecycle, from deployment to Day 2 operations. For more information on Juju security hardening, see the [Juju security](https://canonical.com/juju/docs/juju-cli/3.6/explanation/juju-security/) page and the [How to harden your deployment](https://canonical.com/juju/docs/juju-cli/latest/howto/manage-your-juju-deployment/harden-your-juju-deployment/) guide.

#### Cloud credentials

When configuring credentials for Juju, ensure that users have only the permissions
needed to operate the target substrate. Juju superusers responsible for bootstrapping
and managing controllers require elevated permissions.

| Cloud     | Cloud user policies                                                                                                                                                                                                                            |
|-----------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| OpenStack | N/A                                                                                                                                                                                                                                            |
| AWS       | [Juju on AWS](https://canonical.com/juju/docs/juju-cli/3.6/reference/cloud/list-of-supported-clouds/amazon-ec2/) | 
| Azure     | [Juju on Azure](https://canonical.com/juju/docs/juju-cli/3.6/reference/cloud/list-of-supported-clouds/microsoft-azure/)                                                         |

On Kubernetes, the Juju identity used to bootstrap and manage deployments must
be able to create, delete, patch, and list the required namespaces, Services,
Deployments, StatefulSets, Pods, and PersistentVolumeClaims. An administrative
Kubernetes role is commonly used for this purpose.

#### Juju users

It is very important that Juju users are set up with minimal permissions depending on the scope of their operations. 
Please refer to the [User access levels](https://canonical.com/juju/docs/juju-cli/3.6/reference/user/) documentation for more information on the access levels and corresponding abilities. 

Juju user credentials must be stored securely and rotated regularly to limit the chances of unauthorised access due to credentials leakage.

## Applications

In the following, we provide guidance on how to harden your deployment using:

1. Operating system
2. Security upgrades
3. Encryption 
4. Authentication
5. Monitoring and auditing

### Operating system and base image

Both charms use Ubuntu 24.04 LTS. On VM, deploy a
[Landscape Client Charm](https://charmhub.io/landscape-client) to connect the
underlying machine to Landscape and manage security upgrades and Ubuntu Pro
subscriptions. On K8s, the workload runs in the
[Charmed Apache Kafka rock](https://github.com/canonical/charmed-kafka-rock/pkgs/container/charmed-kafka),
a Rockcraft-based OCI image containing Canonical's Apache Kafka distribution.

### Security upgrades

The VM charm installs a pinned revision of the
[Charmed Apache Kafka snap](https://snapcraft.io/charmed-kafka), while the K8s
charm uses a pinned revision of the OCI image. Both approaches provide a
reproducible and secure environment.

New versions of Charmed Apache Kafka may be released to provide patching of vulnerabilities (CVEs).
It is important to refresh the charm regularly to make sure the workload is as secure as possible. 
For more information on how to refresh the charm, see the [how-to upgrade](how-to-upgrade) guide.

### Encryption

For most production settings, Charmed Apache Kafka should be deployed with encryption enabled. 
To do that, you need to relate Charmed Apache Kafka to one of the TLS certificate operator charms. 
Please refer to the [Charming Security page](https://charmhub.io/topics/security-with-x-509-certificates) for more information on how to select the right certificate
provider for your use case. 

For more information on encryption, see the [Cryptography](cryptography) explanation page and the [How to enable client encryption](how-to-tls-encryption) guide.

### Authentication

Charmed Apache Kafka supports the following authentication layers:

1. [SCRAM-based SASL Authentication](how-to-client-connections)
2. [certificate-based Authentication (mTLS)](how-to-create-mtls-client-credentials)
3. OAuth authentication through an identity provider

The current [Canonical Identity Platform OAuth guide](how-to-enable-oauth)
covers VM deployment only.

Each combination of authentication scheme and encryption is associated with the dedicated listener and it maps to a well-defined port. See the [listeners reference documentation](reference-broker-listeners) for more information.

### Monitoring and auditing

Charmed Apache Kafka provides native integration with the [Canonical Observability Stack (COS)](https://charmhub.io/topics/canonical-observability-stack).
To reduce the blast radius of infrastructure disruptions, the general recommendation is to deploy COS and the observed application into separate environments, isolated from one another. Refer to the [COS production deployments best practices](https://charmhub.io/topics/canonical-observability-stack/reference/best-practices)
for more information.

For instructions, see the [How to integrate the Charmed Apache Kafka deployment with COS](how-to-monitoring-enable-monitoring) and [How to customise the alerting rules and dashboards](how-to-monitoring-integrate-alerts-and-dashboards) guides.

External user access to Apache Kafka is logged to the `kafka-authorizer.log` that is pushed to a [Loki endpoint](https://charmhub.io/loki-k8s) and exposed via [Grafana](https://charmhub.io/grafana), both components being part of the COS stack.

Access denials are logged at the `INFO` level, whereas allowed accesses are logged at the `DEBUG` level.
Depending on the auditing needs, customise the logging level either for all logs via the
`log-level` configuration option ([VM](https://charmhub.io/kafka/configure?channel=4/stable#log-level), [K8s](https://charmhub.io/kafka-k8s/configure?channel=4/stable#log-level)) or
only tune the logging level of the `authorizerAppender` in the `log4j2.yaml` file. See
the [file system paths](reference-file-system-paths) for further information.

## Additional resources

For details on the cryptography used by Charmed Apache Kafka, see the [Cryptography](cryptography) explanation page.
