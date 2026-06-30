# Charmed Kafka Connect K8s Operator

[![Release](https://github.com/canonical/kafka-connect-k8s-operator/actions/workflows/release.yaml/badge.svg)](https://github.com/canonical/kafka-connect-k8s-operator/actions/workflows/release.yaml)
[![Tests](https://github.com/canonical/kafka-connect-k8s-operator/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/canonical/kafka-connect-k8s-operator/actions/workflows/ci.yaml?query=branch%3Amain)

The Charmed Kafka Connect K8s Operator delivers automated operations management from day 0 to day 2 on [Kafka Connect](https://kafka.apache.org/documentation/#connect).

This operator can be found on [Charmhub](https://charmhub.io/kafka-connect) and it comes with production-ready features such as:

- Automated or manual connector plugins management.
- Fault-tolerance, replication and scalability out of the box.
- Authentication on REST API enabled by default.
- TLS support both on the REST API and Apache Kafka cluster relations.
- Seamless integration with Charmed Apache Kafka set of operators
- Seamless integration with an ecosystem of of Integrator charms supporting common ETL tasks on different database technologies offered by [Canonical Data Platform](https://canonical.com/data).

The Charmed Kafka Connect K8s Operator uses the latest [`charmed-kafka` snap](https://github.com/canonical/charmed-kafka-snap) containing Apache Kafka distributed by Canonical.

Since Kafka Connect requires a running Apache Kafka cluster, this charmed operator makes use of the [Charmed Apache Kafka K8s Operator](https://github.com/canonical/kafka-k8s-operator) in order to function.

## Usage

Before using Charmed Kafka Connect, an Apache Kafka cluster needs to be deployed. The Charmed Apache Kafka K8s operator can be deployed as follows:

```bash
juju deploy kafka-k8s --channel 3/edge -n 3 --config roles="broker,controller" --trust
```

To deploy the Charmed Kafka Connect K8s operator and relate it with the Apache Kafka cluster, use the following commands:

```bash
juju deploy kafka-connect-k8s --channel latest/edge --trust
juju integrate kafka-connect-k8s kafka-k8s
```

To watch the process, `juju status` can be used. Once all the units show as `active|idle`, the Kafka Connect cluster is ready to be used.

### Plugin management

Kafka Connect uses a pluggable architecture model, meaning that the user could add desired functionalities by means of **Plugins**, also known as **Connectors**. Simply put, plugins are bundles of JAR files adhering to Kafka Connect Connector Interface. These connectors could be an implementation of a data source connector, data sink connector, a transformer or a converter. Kafka Connect automatically discovers added plugins, and the user could use the exposed REST interface to define desired ETL tasks based on available plugins.

In the Charmed Kafka Connect K8s operator, adding a plugin is as simple as calling the `juju attach-resource` command. Make sure that you bundle all required JAR files into a single TAR archive (for example, `my-plugin.tar`) and then use the following command:

```bash
juju attach-resource kafka-connect-k8s connect-plugin=./my-plugin.tar
```

This will trigger a restart of the `kafka-connect-k8s` charm. Once all units are shown as `active|idle`, your new plugin is ready for use. 

While any plugin can be manually uploaded, for common use-cases of ETL tasks on Data Platform charmed operators we recommend using the [Template Connect Integrator](https://github.com/canonical/template-connect-integrator) charm.

### User management via REST API

Kafka Connect uses a RESTful API for common administrative tasks. By default, Charmed Kafka Connect enforces HTTP Basic authentication on this API.

Internal users on the Charmed Kafka Connect application could be managed using [Juju user secrets](https://documentation.ubuntu.com/juju/latest/reference/secret/index.html#user). 

The secret data should contain a mapping of `username=password`s and access to the secret should be granted to the Kafka Connect application. Then, the Kafka Connect application should be configured to use the user secret by setting the `system-users` config option.

The complete flow for defining custom credentials for the Charmed Kafka Connect application is as follows: 

Add a user secret defining the internal `admin` user's password:

```bash
juju add-secret mysecret admin=adminpass
```

You will receive a secret-id in response which looks like: 

```text
secret:cvh7kruupa1s46bqvuig
```

Then, grant access to the secret with:

```bash
juju grant-secret mysecret kafka-connect-k8s
```

Finally, configure the Kafka Connect application to use the provided secret:

```bash
juju config kafka-connect-k8s system-users=secret:cvh7kruupa1s46bqvuig
```

To verify that Kafka Connect is properly configured and functioning, send a request to the REST interface listing all registered connectors using the password set in Juju secret:

```bash
curl -u admin:adminpass -X GET http://<kafka-connect-k8s-unit-ip>:8083/connector-plugins
```

You should get a response like below:

```bash
[
  {
    "class": "org.apache.kafka.connect.mirror.MirrorCheckpointConnector",
    "type": "source",
    "version": "3.9.0-ubuntu1"
  },
  {
    "class": "org.apache.kafka.connect.mirror.MirrorHeartbeatConnector",
    "type": "source",
    "version": "3.9.0-ubuntu1"
  },
  {
    "class": "org.apache.kafka.connect.mirror.MirrorSourceConnector",
    "type": "source",
    "version": "3.9.0-ubuntu1"
  }
]
```

## Relations

The Charmed Kafka Connect K8s Operator supports Juju [relations](https://documentation.ubuntu.com/juju/latest/reference/relation/) for interfaces listed below.

### The `connect_client` interface

The `connect_client` interface is used with any requirer/integrator charm which has the capability of integration with Charmed Kafka Connect and possibly, one or more other [Data Platform charms](https://canonical.com/data). Integrators will automatically handle connectors/tasks lifecycle on Kafka Connect including plugin management, startup, cleanup, and scaling, and simplify common ETL operations on Data Platform line of products.

A curated set of integrators for common ETL use cases within the Canonical Data Platform product line is available in the [Template Connect Integrator](https://github.com/canonical/template-connect-integrator) repository. These integrators support use cases such as loading data to and from MySQL, PostgreSQL, OpenSearch, S3-compatible storage services, and active/passive replication of Apache Kafka topics using MirrorMaker.

### The `tls-certificates` interface

The `tls-certificates` interface could be used with any charm that provides TLS certificate lifecycle management functionality, following [`this specification`](https://github.com/canonical/charm-relation-interfaces/tree/main/docs/json_schemas/tls_certificates/v1). One example is the [`self-signed-certificates`](https://github.com/canonical/self-signed-certificates-operator) operator by Canonical.

Note that TLS can be enabled in three different modes:

- For Kafka Connect REST interface only
- For the relation between Apache Kafka cluster and Kafka Connect
- For both the REST interface and the relation

To enable TLS on the Kafka Connect REST interface, first deploy the TLS charm and relate it to the Charmed Kafka Connect application:

```bash
juju deploy self-signed-certificates
juju integrate self-signed-certificates kafka-connect-k8s
```

To enable TLS on the relation between the Apache Kafka and Kafka Connect clusters: 

```bash
juju integrate self-signed-certificates kafka-k8s
```

To disable TLS on each interface, remove their respective relations:

```bash
juju remove-relation kafka-connect-k8s self-signed-certificates
juju remove-relation kafka-k8s self-signed-certificates
```

> Note: The TLS settings provided here are intended for use with self-signed certificates, which are not recommended for production clusters. For more secure TLS certificate providers, consider using the `tls-certificates-operator` charm. See its [Charmhub page](https://charmhub.io/tls-certificates-operator) for details.

## Monitoring

The Charmed Kafka Connect K8s Operator comes with the [JMX exporter](https://github.com/prometheus/jmx_exporter/).
The metrics can be queried by accessing the `http://<unit-ip>:9100/metrics` endpoints.

Additionally, the charm provides integration with the [Canonical Observability Stack](https://charmhub.io/topics/canonical-observability-stack).

Deploy `cos-lite` bundle in a Kubernetes environment. This can be done by following the [deployment tutorial](https://charmhub.io/topics/canonical-observability-stack/tutorials/install-microk8s). It is needed to offer the endpoints of the COS relations. The [offers-overlay](https://github.com/canonical/cos-lite-bundle/blob/main/overlays/offers-overlay.yaml) can be used, and this step is shown on the COS tutorial.

Once COS is deployed, we can find the offers from the Kafka Connect model. To do that, switch back to that model:

```bash
juju switch <kafka_connect_model_name>
```

And use the `find-offers` command:

```bash
juju find-offers <k8s_controller_name>:
```

The following or similar output will appear, if `micro` is the k8s controller name and `cos` the model where `cos-lite` has been deployed:

```
Store  URL                   Access  Interfaces                         
micro  admin/cos.grafana     admin   grafana_dashboard:grafana-dashboard
micro  admin/cos.prometheus  admin   prometheus_scrape:metrics-endpoint
. . .
```

Now, integrate Kafka Connect application with the `metrics-endpoint`, `grafana-dashboard` and `logging` relations:

```bash
juju integrate micro:admin/cos.prometheus kafka-connect-k8s
juju integrate micro:admin/cos.grafana kafka-connect-k8s
juju integrate micro:admin/cos.loki kafka-connect-k8s
```

After this is complete, Grafana will show a new dashboard: `Kafka Connect Cluster`.

## Contributing

Please see the [Juju SDK docs](https://juju.is/docs/sdk) for guidelines on enhancements to this charm following best practice guidelines, and [CONTRIBUTING.md](https://github.com/canonical/kafka-connect-k8s-operator/blob/main/CONTRIBUTING.md) for developer guidance.

### We are Hiring!

Also, if you truly enjoy working on open-source projects like this one and you would like to be part of the OSS revolution, please don't forget to check out the [open positions](https://canonical.com/careers/all) we have at [Canonical](https://canonical.com/). 

## License

The Charmed Kafka Connect K8s Operator is free software, distributed under the Apache Software License, version 2.0. See [LICENSE](https://github.com/canonical/kafka-connect-k8s-operator/blob/main/LICENSE) for more information.
