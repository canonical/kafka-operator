# Security Hardening Guide

This document provides an overview of security features and guidance for hardening the security of [Charmed Apache Kafka](https://github.com/canonical/kafka-bundle) deployments, including setting up and managing a secure environment.

## Environment

The environment where Charmed Apache Kafka operates can be divided into two components:

1. Cloud
2. Juju 

### Cloud

Charmed Apache Kafka can be deployed on top of several clouds and virtualization layers: 

| Cloud     | Security guides                                                                                                                                                                                                                                                         |
|-----------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| OpenStack | [OpenStack Security Guide](https://docs.openstack.org/security-guide/)                                                                                                                                                                                                 |
| AWS       | [Best Practices for Security, Identity and Compliance](https://aws.amazon.com/architecture/security-identity-compliance), [AWS security credentials](https://docs.aws.amazon.com/IAM/latest/UserGuide/security-creds.html#access-keys-and-secret-access-keys)          | 
| Azure     | [Azure security best practices and patterns](https://learn.microsoft.com/en-us/azure/security/fundamentals/best-practices-and-patterns), [Managed identities for Azure resource](https://learn.microsoft.com/en-us/entra/identity/managed-identities-azure-resources/) |

### Juju 

Juju is the component responsible for orchestrating the entire lifecycle, from deployment to Day 2 operations. For more information on Juju security hardening, see the [Juju security](/t/juju-security/15684) page and the [How to harden your deployment](https://juju.is/docs/juju/harden-your-deployment) guide.

#### Cloud credentials

When configuring cloud credentials to be used with Juju, ensure that users have correct permissions to operate at the required level. 
Juju superusers responsible for bootstrapping and managing controllers require elevated permissions to manage several kinds of resources, such as
virtual machines, networks, storages, etc. Please refer to the links below for more information on the policies required to be used depending on the cloud. 

| Cloud     | Cloud user policies                                                                                                                                                                                                                            |
|-----------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| OpenStack | N/A                                                                                                                                                                                                                                            |
| AWS       | [Juju AWS Permission](/t/juju-aws-permissions/5307), [AWS Instance Profiles](/t/using-aws-instance-profiles-with-juju-2-9/5185), [Juju on AWS](https://juju.is/docs/juju/amazon-ec2) | 
| Azure     | [Juju Azure Permission](https://juju.is/docs/juju/microsoft-azure), [How to use Juju with Microsoft Azure](/t/how-to-use-juju-with-microsoft-azure/15219)                                                         |

#### Juju users

It is very important that Juju users are set up with minimal permissions depending on the scope of their operations. 
Please refer to the [User access levels](https://juju.is/docs/juju/user-permissions) documentation for more information on the access levels and corresponding abilities. 

Juju user credentials must be stored securely and rotated regularly to limit the chances of unauthorized access due to credentials leakage.

## Applications

In the following, we provide guidance on how to harden your deployment using:

1. Operating system
2. Security upgrades
3. Encryption 
4. Authentication
5. Monitoring and auditing

### Operating system

Charmed Apache Kafka and Charmed Apache ZooKeeper currently run on top of Ubuntu 22.04. Deploy a [Landscape Client Charm](https://charmhub.io/landscape-client?) to 
connect the underlying VM to a Landscape User Account to manage security upgrades and integrate [Ubuntu Pro](https://ubuntu.com/pro) subscriptions. 

### Security upgrades

Charmed Apache Kafka and Charmed Apache ZooKeeper operators install a pinned revision of the [Charmed Apache Kafka snap](https://snapcraft.io/charmed-kafka)
and [Charmed ZooKeeper snap](https://snapcraft.io/charmed-zookeeper), respectively, to provide reproducible and secure environments. 

New versions of Charmed Apache Kafka and Charmed Apache ZooKeeper may be released to provide patching of vulnerabilities (CVEs). 
It is important to refresh the charm regularly to make sure the workload is as secure as possible. 
For more information on how to refresh the charm, see the [how-to upgrade](https://charmhub.io/kafka/docs/h-upgrade) guide.

### Encryption

Charmed Apache Kafka must be deployed with encryption enabled. 
To do that, you need to relate Charmed Apache Kafka and Charmed Apache ZooKeeper to one of the TLS certificate operator charms. 
Please refer to the [Charming Security page](https://charmhub.io/topics/security-with-x-509-certificates) for more information on how to select the right certificate
provider for your use case. 

For more information on encryption, see the [Cryptography](/t/charmed-apache-kafka-documentation-explanation-security/15714) explanation page and the [How to enable encryption](/t/charmed-apache-kafka-documentation-how-to-enable-encryption/10281) guide.

### Authentication

Charmed Apache Kafka supports the following authentication layers:

1. [SCRAM-based SASL Authentication](/t/charmed-kafka-how-to-manage-app/10285)
2. [certificate-base Authentication (mTLS)](/t/create-mtls-client-credentials/11079)
3. OAuth Authentication using [Hydra](/t/how-to-connect-to-kafka-using-hydra-as-oidc-provider/14610) or [Google](/t/how-to-connect-to-kafka-using-google-as-oidc-provider/14611)

Each combination of authentication scheme and encryption is associated with the dedicated listener and it maps to a well-defined port. See the [listener reference documentation](/t/charmed-kafka-documentation-reference-listeners/13264) for more information. 

### Monitoring and Auditing

Charmed Apache Kafka provides native integration with the [Canonical Observability Stack (COS)](https://charmhub.io/topics/canonical-observability-stack).
To reduce the blast radius of infrastructure disruptions, the general recommendation is to deploy COS and the observed application into separate environments, isolated from one another. Refer to the [COS production deployments best practices](https://charmhub.io/topics/canonical-observability-stack/reference/best-practices)
for more information. 

For instructions, see the [How to integrate the Charmed Apache Kafka deployment with COS](/t/charmed-kafka-how-to-enable-monitoring/10283) and [How to customise the alerting rules and dashboards](/t/charmed-kafka-documentation-how-to-integrate-custom-alerting-rules-and-dashboards/13431) guides.

External user access to Apache Kafka is logged to the `kafka-authorizer.log` that is pushed to [Loki endpoint](https://charmhub.io/loki-k8s) and exposed via [Grafana](https://charmhub.io/grafana), both components being part of the COS stack.

Access denials are logged at the `INFO` level, whereas allowed accesses are logged at the `DEBUG` level. Depending on the auditing needs, 
customize the logging level either for all logs via the [`log_level`](https://charmhub.io/kafka/configurations?channel=3/stable#log_level) config option or 
only tune the logging level of the `authorizerAppender` in the `log4j.properties` file. See
the [file system paths](/t/charmed-kafka-documentation-reference-file-system-paths/13262) for further information.

## Additional Resources

For details on the cryptography used by Charmed Apache Kafka, see the [Cryptography](/t/charmed-apache-kafka-documentation-explanation-security/15714) explanation page.