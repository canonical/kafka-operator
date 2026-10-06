# Charmed Apache Kafka K8s Operator

[![CharmHub Badge](https://charmhub.io/kafka-k8s/badge.svg)](https://charmhub.io/kafka-k8s)
[![Release](https://github.com/canonical/kafka-k8s-operator/actions/workflows/release.yaml/badge.svg)](https://github.com/canonical/kafka-k8s-operator/actions/workflows/release.yaml)
[![Tests](https://github.com/canonical/kafka-k8s-operator/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/canonical/kafka-k8s-operator/actions/workflows/ci.yaml?query=branch%3Amain)
[![Docs](https://readthedocs.com/projects/canonical-charmed-kafka-k8s/badge/?version=3)](https://app.readthedocs.com/projects/canonical-charmed-kafka-k8s/builds/?version__slug=3)

## Overview

Charmed Apache Kafka K8s delivers automated operations management [from Day 0 to Day 2](https://codilime.com/blog/day-0-day-1-day-2-the-software-lifecycle-in-the-cloud-age/) on the [Apache Kafka](https://kafka.apache.org) event streaming platform deployed on top of a [Kubernetes cluster](https://kubernetes.io/). It is an open source, end-to-end, production ready data platform on top of cloud native technologies.

The Charmed Operator can be found on [Charmhub](https://charmhub.io/kafka-k8s) and it comes with features such as:

- Fault-tolerance, replication, scalability and high-availability out-of-the-box.
- SASL/SCRAM auth for Broker-Broker and Client-Broker authentication enabled by default.
- Access control management supported with user-provided ACL lists.

As currently Apache Kafka requires a paired Apache ZooKeeper deployment in production, this operator makes use of the [Charmed Apache ZooKeeper K8s](https://github.com/canonical/zookeeper-k8s-operator) for various essential functions.

## Requirements

For production environments, it is recommended to deploy at least 5 nodes for Apache Zookeeper and 3 for Apache Kafka.

The following minimum requirements are meant to be for a production environment:

- 64GB of RAM
- 24 cores
- 12 storage devices
- 10 Gb Ethernet card

The charm can be deployed in much smaller environments if needed.

## Usage

This section demonstrates basic usage of Charmed Apache Kafka K8s. 
For more information on how to perform typical tasks, see the How to guides section of the [Charmed Apache Kafka K8s documentation](https://canonical.com/data/docs/kafka/k8s).

### Deployment

The Apache Kafka and Apache ZooKeeper operators can both be deployed as follows:

```shell
juju deploy zookeeper-k8s -n 5
juju deploy kafka-k8s -n 3
```

After this, it is necessary to connect them:

```shell
juju integrate kafka-k8s zookeeper-k8s
```

To watch the process, the `juju status` command can be used. Once all the units shown as `active|idle`, the credentials to access a broker can be queried with:

```shell
juju run kafka-k8s/leader get-admin-credentials
```

### Scaling

The charm can be scaled using `juju scale-application` command:

```shell
juju scale-application kafka-k8s <num_of_units_to_scale_to>
```

This will add or remove brokers to match the required number. For example, to scale a deployment with 3 kafka units to 5, run:

```shell
juju scale-application kafka-k8s 5
```

### Password rotation

The operator user is used internally by the Charmed Apache Kafka K8s Operator. The `set-password` action can be used to rotate its password:

```shell
juju run kafka-k8s/leader set-password password=<password>
```

Use the same action without a password parameter to randomly generate a password for the operator user.

### Storage support

Currently, Charmed Apache Kafka K8s makes use of a 10 GB storage mount, tied to a [Kubernetes PVC](https://kubernetes.io/docs/concepts/storage/persistent-volumes/).

This storage is mounted on `/var/lib/data/kafka` and used for log-data.

Service logs can be found in `/var/log/kafka`.

## Relations

The Charmed Apache Kafka K8s Operator supports Juju [relations](https://juju.is/docs/olm/relations) for interfaces listed below.

#### The kafka_client interface

The `kafka_client` interface is used with the [Data Integrator](https://charmhub.io/data-integrator) charm, which upon relation automatically provides credentials and endpoints for connecting to the desired product.

To deploy the `data-integrator` charm with the desired `topic-name` and user roles: 

```shell
juju deploy data-integrator
juju config data-integrator topic-name=test-topic extra-user-roles=producer,consumer
```

To integrate the two applications:

```shell
juju integrate data-integrator kafka-k8s
```

To retrieve information, enter:

```shell
juju run data-integrator/leader get-credentials
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

```shell 
juju deploy tls-certificates-operator
```

Then, add the necessary configurations:

```shell
juju config tls-certificates-operator generate-self-signed-certificates="true" ca-common-name="Test CA" 
```

And enable TLS by relating the two applications to the `tls-certificates` charm:

```shell
juju integrate tls-certificates-operator zookeeper-k8s
juju integrate tls-certificates-operator kafka-k8s
```

Now you can generate shared internal key:

```shell
openssl genrsa -out internal-key.pem 3072
```

And apply keys on each Charmed Apache Kafka K8s unit:

```shell
# 
juju run kafka-k8s/0 set-tls-private-key "internal-key=$(base64 -w0 internal-key.pem)"
juju run kafka-k8s/1 set-tls-private-key "internal-key=$(base64 -w0 internal-key.pem)"
juju run kafka-k8s/2 set-tls-private-key "internal-key=$(base64 -w0 internal-key.pem)"
```

To disable TLS remove the relation:

```shell
juju remove-relation kafka-k8s tls-certificates-operator
juju remove-relation zookeeper-k8s tls-certificates-operator
```

> **Note**: The TLS settings here are for self-signed-certificates which are not recommended for production clusters, the `tls-certificates-operator` charm offers a variety of configurations, read more on the TLS charm in the [documentation](https://charmhub.io/tls-certificates-operator).

## Monitoring

The Charmed Apache Kafka K8s comes with several exporters by default. The metrics can be queried by accessing the following endpoints:

- JMX exporter: `http://<pod-ip>:9101/metrics`

Additionally, the charm provides integration with the [Canonical Observability Stack](https://charmhub.io/topics/canonical-observability-stack).

Deploy `cos-lite` bundle in a Kubernetes environment. This can be done by following the [deployment tutorial](https://charmhub.io/topics/canonical-observability-stack/tutorials/install-microk8s). It is needed to offer the endpoints of the COS relations. The [offers-overlay](https://github.com/canonical/cos-lite-bundle/blob/main/overlays/offers-overlay.yaml) can be used, and this step is shown on the COS tutorial.

Once COS is deployed, we can find the offers from the Apache Kafka model. To do that, switch back to the kafka model:

```shell
juju switch <kafka_model_name>
```

And use the `find-offers` command:

```shell
juju find-offers <k8s_controller_name>:
```

The following or similar output will appear, if `micro` is the k8s controller name and `cos` the model where `cos-lite` has been deployed:

```
Store  URL                   Access  Interfaces                         
micro  admin/cos.grafana     admin   grafana_dashboard:grafana-dashboard
micro  admin/cos.prometheus  admin   prometheus_scrape:metrics-endpoint
. . .
```

Now, integrate kafka with the `metrics-endpoint`, `grafana-dashboard` and `logging` relations:

```shell
juju integrate micro:admin/cos.prometheus kafka-k8s
juju integrate micro:admin/cos.grafana kafka-k8s
juju integrate micro:admin/cos.loki kafka-k8s
```

After this is complete, Grafana will show a new dashboard: `Kafka JMX Metrics`.

## Security

For an overview of security features of the Charmed Apache Kafka K8s, see the [Security page](https://canonical.com/data/docs/kafka/k8s/e-security) in the Explanation section of the documentation.

Security issues in the Charmed Apache Kafka K8s operator can be reported through [Launchpad](https://wiki.ubuntu.com/DebuggingSecurity#How_to_File). Please do not file GitHub issues about security issues.

## Performance tuning

For information on tuning performance of Charmed Apache Kafka K8s, see the [Performance tuning reference](https://discourse.charmhub.io/t/charmed-kafka-documentation-reference-performace-tuning/10561) page.

## Contributing

Please see the [Juju SDK docs](https://juju.is/docs/sdk) for guidelines on enhancements to this charm following best practice guidelines, and [CONTRIBUTING.md](https://github.com/canonical/kafka-k8s-operator/blob/main/CONTRIBUTING.md) for developer guidance.

## License

Charmed Apache Kafka K8s is free software, distributed under the Apache Software License, version 2.0. For more information, see the [LICENSE](https://github.com/canonical/kafka-k8s-operator/blob/main/LICENSE) file.
