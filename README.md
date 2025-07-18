# Charmed Apache Kafka Operator

[![CharmHub Badge](https://charmhub.io/kafka/badge.svg)](https://charmhub.io/kafka)
[![Release](https://github.com/canonical/kafka-operator/actions/workflows/release.yaml/badge.svg)](https://github.com/canonical/kafka-operator/actions/workflows/release.yaml)
[![Tests](https://github.com/canonical/kafka-operator/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/canonical/kafka-operator/actions/workflows/ci.yaml?query=branch%3Amain)
[![Docs](https://readthedocs.com/projects/canonical-charmed-kafka/badge/?version=main&style=plastic)](https://app.readthedocs.com/projects/canonical-charmed-kafka/builds/?version__slug=main)

## Overview

The Charmed Apache Kafka Operator delivers automated operations management [from Day 0 to Day 2](https://codilime.com/blog/day-0-day-1-day-2-the-software-lifecycle-in-the-cloud-age/) on the [Apache Kafka](https://kafka.apache.org) event streaming platform. It is an open source, end-to-end, production ready data platform on top of cloud native technologies.

The Charmed Operator can be found on [Charmhub](https://charmhub.io/kafka) and it comes with production-ready features such as:

- Fault-tolerance, replication, scalability and high-availability out-of-the-box.
- SASL/SCRAM auth for Broker-Broker and Client-Broker authentication enabled by default.
- Access control management supported with user-provided ACL lists.

### Features checklist

The following are some of the most important planned features and their implementation status:

- [x] Super-user creation
- [x] Inter-broker auth
- [x] Horizontally scale brokers
- [x] Username/Password creation for related applications
- [x] Automatic topic creation with associated user ACLs
- [x] Persistent storage support with [Juju Storage](https://juju.is/docs/olm/defining-and-using-persistent-storage)
- [x] TLS/SSL encrypted connections
- [x] mTLS
- [ ] Multi-application clusters
- [ ] Partition rebalancing during broker scaling

## Requirements

For production environments, it is recommended to deploy at least 5 nodes of Apache Kafka as **controllers** and 3 nodes of Apache Kafka as **brokers**.

The following requirements are meant to be for production environment:

- 64GB of RAM
- 24 cores
- 12 storage devices
- 10 Gb Ethernet card

The charm can be deployed in much smaller environments if needed. For more information on requirements and version compartibility, see the [Requirements](https://discourse.charmhub.io/t/charmed-kafka-documentation-reference-requirements/10563) page.

## Usage

This section demonstrates basic usage of the Charmed Apache Kafka operator. 
For more information on how to perform typical tasks, see the How to guides section of the [Charmed Apache Kafka documentation](https://canonical.com/data/docs/kafka/iaas).

### Deployment

Charmed Apache Kafka can be deployed as follows:

```bash
juju deploy kafka -n 5 --config roles="controller" controller
juju deploy kafka -n 3 --config roles="broker"
```

After this, it is necessary to integrate them:

```bash
juju integrate kafka:peer-cluster-orchestrator controller:peer-cluster
```

To watch the process, the `juju status` command can be used. Once all the units are shown as `active|idle`, the credentials to access a broker can be set using Juju secrets, discussed in the **Password Rotation** section.

Apache Kafka ships with `bin/*.sh` commands to do various administrative tasks, e.g `bin/kafka-config.sh` to update cluster configuration, `bin/kafka-topics.sh` for topic management, and many more! Charmed Apache Kafka provides these commands for administrators to run their desired cluster configurations securely with SASL authentication, either from within the cluster or as an external client.

For example, to list the current topics on the Apache Kafka cluster, run the following command:

```bash
juju ssh kafka/leader 'sudo charmed-kafka.topics \
    --bootstrap-server $(hostname -i):19093 \
    --command-config $CONF/client.properties \
    --list'
```

Note that Charmed Apache Kafka cluster is secure-by-default: when no other application is related to Charmed Apache Kafka, listeners are disabled, thus preventing any incoming connection. However, even for running the commands above, listeners must be enabled. If there are no other applications, you can deploy a `data-integrator` charm and relate it to Charmed Apache Kafka to enable listeners.

Available Charmed Apache Kafka bin commands can be found with:

```bash
snap info charmed-kafka
```

### Scaling

The charm can be scaled out using `juju add-unit` command:

```bash
juju add-unit kafka -n <num_of_desired_units>
```

This will add brokers to match the required number. For example, to scale a deployment with three kafka units to five, run:

```bash
juju add-unit kafka -n 2
```

Even when scaling multiple units at the same time, the charm uses a rolling restart sequence to make sure the cluster stays available and healthy during the operation.

### Password rotation

The `admin` user is used internally by the Charmed Apache Kafka Operator. The password for this user can be set using Juju secrets. The process to set or change the password is described below.  

First, add a custom secret for the internal `admin` user with your desired password:

```bash
juju add-secret mysecret admin=My$trongP4ss
```

You will receive a secret ID in response, for example: 

```text
secret:cvh7kruupa1s46bqvuig
```

Then, grant access to the secret with:

```bash
juju grant-secret mysecret kafka
```

Finally, configure the Apache Kafka application to use the provided secret:

```bash
juju config kafka system-users=secret:cvh7kruupa1s46bqvuig
```


### Storage support

Currently, the Charmed Apache Kafka Operator supports 1 or more storage volumes. A 10G storage volume will be installed by default for `log.dirs`.
This is used for logs storage, mounted on `/var/snap/kafka/common`

When storage is added or removed, the Apache Kafka service will restart to ensure it uses the new volumes. Additionally, logs and charm status messages will prompt users to manually reassign partitions so that the new storage volumes are populated. By default, Apache Kafka will not assign partitions to new directories/units until existing topic partitions are assigned to it, or a new topic is created.

## Relations

The Charmed Apache Kafka Operator supports Juju [relations (integrations)](https://documentation.ubuntu.com/juju/latest/reference/relation/) for interfaces listed below.

#### The Kafka_client interface

The `kafka_client` interface is used with the [Data Integrator](https://charmhub.io/data-integrator) charm, which upon relation automatically provides credentials and endpoints for connecting to the desired product.

To deploy the `data-integrator` charm with the desired `topic-name` and user roles:

```bash
juju deploy data-integrator
juju config data-integrator topic-name=test-topic extra-user-roles="producer,consumer"
```

To integrate the two applications:

```bash
juju integrate data-integrator kafka
```

To retrieve information, enter:

```bash
juju run data-integrator/leader get-credentials --wait
```

The output looks like this:

```yaml
unit-data-integrator-0:
  UnitId: data-integrator/0
  id: "4"
  results:
    kafka:
      consumer-group-prefix: relation-27-
      endpoints: 10.123.8.133:19092
      password: ejMp4SblzxkMCF0yUXjaspneflXqcyXK
      tls: disabled
      username: relation-27
      zookeeper-uris: 10.123.8.154:2181,10.123.8.181:2181,10.123.8.61:2181/kafka
    ok: "True"
  status: completed
  timing:
    completed: 2023-01-27 14:22:51 +0000 UTC
    enqueued: 2023-01-27 14:22:50 +0000 UTC
    started: 2023-01-27 14:22:51 +0000 UTC
```

#### The tls-certificates interface

The `tls-certificates` interface is used with the `tls-certificates-operator` charm.

To enable TLS, deploy the TLS charm first:

```bash
juju deploy tls-certificates-operator
```

Then, add the necessary configurations:

```bash
juju config tls-certificates-operator generate-self-signed-certificates="true" ca-common-name="Test CA"
```

And enable TLS by relating the two applications to the `tls-certificates` charm:

```bash
juju integrate tls-certificates-operator kafka:certificates
```

Updates to private keys for certificate signing requests (CSR) can be made via the `set-tls-private-key` action:

```bash
# Updates can be done with auto-generated keys with
juju run kafka/0 set-tls-private-key --wait
juju run kafka/1 set-tls-private-key --wait
juju run kafka/2 set-tls-private-key --wait
```

Now you can generate shared internal key:

```bash
openssl genrsa -out internal-key.pem 3072
```

Passing keys to external/internal keys should *only be done with* `base64 -w0` *not* `cat`.

Apply keys on each Charmed Apache Kafka unit:

```bash
juju run kafka/0 set-tls-private-key "internal-key=$(base64 -w0 internal-key.pem)" --wait
juju run kafka/1 set-tls-private-key "internal-key=$(base64 -w0 internal-key.pem)" --wait
juju run kafka/2 set-tls-private-key "internal-key=$(base64 -w0 internal-key.pem)" --wait
```

To disable TLS remove the relation:

```bash
juju remove-relation kafka tls-certificates-operator
```

> **Note**: The TLS settings here are for self-signed-certificates which are not recommended for production clusters, the `tls-certificates-operator` charm offers a variety of configurations, read more on the TLS charm in the [documentation](https://charmhub.io/tls-certificates-operator).

## Monitoring

The Charmed Apache Kafka Operator comes with the [JMX exporter](https://github.com/prometheus/jmx_exporter/).
The metrics can be queried by accessing the `http://<unit-ip>:9101/metrics` endpoints.

Additionally, the charm provides integration with the [Canonical Observability Stack](https://charmhub.io/topics/canonical-observability-stack).

Deploy the `cos-lite` bundle in a Kubernetes environment. This can be done by following the
[deployment tutorial](https://charmhub.io/topics/canonical-observability-stack/tutorials/install-microk8s).
Since the Charmed Apache Kafka Operator is deployed on a machine environment, it is needed to offer the endpoints
of the COS relations. The [offers-overlay](https://github.com/canonical/cos-lite-bundle/blob/main/overlays/offers-overlay.yaml)
can be used, and this step is shown in the COS tutorial.

Next, deploy [Grafana Agent](https://charmhub.io/grafana-agent) and follow the
[tutorial](https://discourse.charmhub.io/t/using-the-grafana-agent-machine-charm/8896)
to relate it to the COS Lite offers.

Now, integrate Apache Kafka with the Grafana Agent:

```bash
juju integrate kafka grafana-agent
```

After this is complete, Grafana will show two new dashboards: `Kafka Metrics` and `Node Exporter Kafka`.

## Security

For an overview of security features of the Charmed Apache Kafka Operator, see the [Security page](https://canonical.com/data/docs/kafka/iaas/e-security) in the Explanation section of the documentation.

Security issues in the Charmed Apache Kafka Operator can be reported through [Launchpad](https://wiki.ubuntu.com/DebuggingSecurity#How_to_File). Please do not file GitHub issues about security issues.

## Performance tuning

For information on tuning performance of Charmed Apache Kafka, see the [Performance tuning reference](https://discourse.charmhub.io/t/charmed-kafka-documentation-reference-performace-tuning/10561) page.

## Contributing

Please see the [Juju SDK docs](https://juju.is/docs/sdk) for guidelines on enhancements to this charm following best practice guidelines, and [CONTRIBUTING.md](https://github.com/canonical/kafka-operator/blob/main/CONTRIBUTING.md) for developer guidance. 

Also, if you truly enjoy working on open-source projects like this one, check out the [career options](https://canonical.com/careers/all) we have at [Canonical](https://canonical.com/). 

## License

Charmed Apache Kafka is free software, distributed under the Apache Software License, version 2.0. See [LICENSE](https://github.com/canonical/kafka-operator/blob/main/LICENSE) for more information.
