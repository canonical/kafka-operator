# Enable Monitoring

Both Charmed Kafka and Charmed ZooKeeper comes with the [JMX exporter](https://github.com/prometheus/jmx_exporter/).
The metrics can be queried by accessing the `http://<kafka-unit-ip>:9101/metrics` and `http://<zookeeper-unit-ip>:9998/metrics` endpoints, respectively.

Additionally, the charm provides integration with the [Canonical Observability Stack](https://charmhub.io/topics/canonical-observability-stack).

Deploy cos-lite bundle in a Kubernetes environment. This can be done by following the
[deployment tutorial](https://charmhub.io/topics/canonical-observability-stack/tutorials/install-microk8s).
Since the Charmed Kafka Operator is deployed directly on a cloud infrastructure environment, it is 
needed to offer the endpoints of the COS relations. The [offers-overlay](https://github.com/canonical/cos-lite-bundle/blob/main/overlays/offers-overlay.yaml)
can be used, and this step is shown in the COS tutorial.

Switch to COS K8s environment and offer COS interfaces to be cross-model related with Charmed Kafka VM model:
```shell
# Switch to Kubernetes controller, for the cos model.
juju switch <k8s_controller>:<cos_model_name>

juju offer grafana:grafana-dashboard grafana-dashboards
juju offer loki:logging loki-logging
juju offer prometheus:receive-remote-write prometheus-receive-remote-write
```

Switch to Charmed Kafka VM model, find offers and relate with them:
```shell
# We are on the Kubernetes controller, for the cos model. Switch to kafka model
juju switch <machine_controller_name>:<kafka_model_name>

juju find-offers <k8s_controller>:
```

A similar output should appear, if `k8s` is the k8s controller name and `cos` the model where `cos-lite` has been deployed:
```shell
Store      URL                                        Access  Interfaces
k8s        admin/cos.grafana-dashboards               admin   grafana_dashboard:grafana-dashboard
k8s        admin/cos.loki-logging                     admin   loki_push_api:logging
k8s        admin/cos.prometheus-receive-remote-write  admin   prometheus-receive-remote-write:receive-remote-write
...
```

Consume offers to be reachable in the current model:
```shell
juju consume <k8s_controller>:admin/<cos_model_name>.prometheus-receive-remote-write
juju consume <k8s_controller>:admin/<cos_model_name>.loki-logging
juju consume <k8s_controller>:admin/<cos_model_name>.grafana-dashboards
```

Now, deploy `grafana-agent` (subordinate charm) and relate it with Charmed Kafka and Charmed ZooKeeper:
```shell
juju deploy grafana-agent
juju relate kafka:cos-agent grafana-agent
juju relate zookeeper:cos-agent grafana-agent
```

Finally, relate `grafana-agent` with consumed COS offers:

```
juju relate grafana-agent grafana-dashboards
juju relate grafana-agent loki-logging
juju relate grafana-agent prometheus-receive-remote-write
```

Wait for all components to settle down on a `active/idle` state on both 
models, e.g. `<kafka_model_name>` and `<cos_model_name>`.

After this is complete, the monitoring COS stack should be up and running and ready to be used. 

### Connect Grafana web interface
To connect to the Grafana web interface, follow the [Browse dashboards](https://charmhub.io/topics/canonical-observability-stack/tutorials/install-microk8s?_ga=2.201254254.1948444620.1704703837-757109492.1701777558#heading--browse-dashboards) section of the MicroK8s "Getting started" guide.
```shell
juju run grafana/leader get-admin-password --model <k8s_cos_controller>:<cos_model_name>
```

## Tune server logging level

In order to tune the level of the server logs for Kafka and ZooKeeper, configure the `log-level` and `log_level` properties accordingly

### Kafka 

```
juju config kafka log_level=<LOG_LEVEL>
```

Possible values are `ERROR`, `WARNING`, `INFO`, `DEBUG`.

### ZooKeeper

```
juju config kafka log-level=<LOG_LEVEL>
```

Possible values are `ERROR`, `WARNING`, `INFO`, `DEBUG`.