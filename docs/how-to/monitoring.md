---
myst:
  html_meta:
    description: "Set up Charmed Apache Kafka monitoring with Canonical Observability Stack - integrate Grafana, Prometheus, and Loki for metrics."
---

(how-to-monitoring)=
# How to set up monitoring

Charmed Apache Kafka comes with the [JMX exporter](https://github.com/prometheus/jmx_exporter/).
Broker metrics can be queried at `http://<kafka-unit-ip>:9101/metrics`. On K8s,
Cruise Control balancer metrics are also available at
`http://<kafka-unit-ip>:9102/metrics`.

Additionally, the charm provides integration with the [Canonical Observability Stack](https://charmhub.io/topics/canonical-observability-stack).

(how-to-monitoring-enable-monitoring)=
## Enable monitoring

Deploy the `cos-lite` bundle in a Kubernetes environment. This can be done by following the
[deployment tutorial](https://charmhub.io/topics/canonical-observability-stack/tutorials/install-microk8s).

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

Because Charmed Apache Kafka is deployed in a VM model, offer the endpoints of
the COS relations from the Kubernetes COS model and consume them in the VM model.

````

````{tab-item} K8s
:sync: k8s

If Charmed Apache Kafka K8s is deployed in the same model as COS, integrate the
applications directly:

```shell
juju integrate kafka-k8s:metrics-endpoint prometheus
juju integrate kafka-k8s:grafana-dashboard grafana
juju integrate kafka-k8s:logging loki
```

If COS is in a separate model, use the cross-model procedure below. On K8s,
an `opentelemetry-collector-k8s` charm is deployed in the Kafka model and
forwards metrics, dashboards, and logs to the consumed COS offers.

````

`````

The [offers-overlay](https://github.com/canonical/cos-lite-bundle/blob/main/overlays/offers-overlay.yaml)
can be used, and this step is shown in the COS tutorial.

### Offer interfaces via the COS controller

Switch to the COS K8s environment and offer COS interfaces to be cross-model related with the Charmed Apache Kafka model:

```shell
juju switch <k8s_controller>:<cos_model_name>

juju offer grafana:grafana-dashboard grafana-dashboards
juju offer loki:logging loki-logging
juju offer prometheus:receive-remote-write prometheus-receive-remote-write
```

### Consume offers via the Apache Kafka model

Switch back to the Charmed Apache Kafka model, find offers and integrate with them:

```shell
juju switch <kafka_controller_name>:<kafka_model_name>

juju find-offers <k8s_controller>:
```

A similar output should appear, if `k8s` is the K8s controller name and `cos` the model where `cos-lite` has been deployed:

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

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

Deploy `opentelemetry-collector` (a subordinate charm) and integrate it with Charmed Apache Kafka:

```shell
juju deploy opentelemetry-collector
juju integrate kafka:cos-agent opentelemetry-collector
```

Finally, relate `opentelemetry-collector` with consumed COS offers:

```shell
juju integrate opentelemetry-collector grafana-dashboards
juju integrate opentelemetry-collector loki-logging
juju integrate opentelemetry-collector prometheus-receive-remote-write
```

````

````{tab-item} K8s
:sync: k8s

Deploy `opentelemetry-collector-k8s` in the Kafka model and integrate it with
Charmed Apache Kafka K8s:

```shell
juju deploy opentelemetry-collector-k8s kafka-cos-agent
juju integrate kafka-k8s:metrics-endpoint kafka-cos-agent
juju integrate kafka-k8s:grafana-dashboard kafka-cos-agent:grafana-dashboards-consumer
juju integrate kafka-k8s:logging kafka-cos-agent:receive-loki-logs
```

```{note}
If the Kafka KRaft controllers run in a separate application, repeat the
`metrics-endpoint`, `grafana-dashboard`, and `logging` integrations for that
application as well.
```

Finally, relate `opentelemetry-collector-k8s` with the consumed COS offers:

```shell
juju integrate kafka-cos-agent:send-remote-write prometheus-receive-remote-write
juju integrate kafka-cos-agent:grafana-dashboards-provider grafana-dashboards
juju integrate kafka-cos-agent:send-loki-logs loki-logging
```

````

`````

Wait for all components to settle down on a `active/idle` state on both models, e.g. `<kafka_model_name>` and `<cos_model_name>`.

After this is complete, the monitoring COS stack should be up and running and ready to be used.

### Connect Grafana web interface

To connect to the Grafana web interface, follow the [Browse dashboards](https://documentation.ubuntu.com/observability/track-2/tutorial/installation/cos-lite-microk8s-sandbox/#browse-dashboards) section of the MicroK8s "Getting started" guide.

```shell
juju run grafana/leader get-admin-password --model <k8s_cos_controller>:<cos_model_name>
```

## Tune server logging level

To tune the level of the server logs for Apache Kafka, configure the `log-level` parameter:

```shell
juju config <KAFKA_APP_NAME> log-level=<LOG_LEVEL>
```

```{tip}
See the `log-level` configuration reference for [VM](https://charmhub.io/kafka/configure?channel=4/stable#log-level)
or [K8s](https://charmhub.io/kafka-k8s/configurations?channel=4/stable#log-level).
```

Possible `LOG_LEVEL` values are: `ERROR`, `WARNING`, `INFO`, and `DEBUG`.

(how-to-monitoring-integrate-alerts-and-dashboards)=
## Alerts and dashboards

This guide shows you how to integrate an existing set of rules and/or dashboards to your Charmed Apache Kafka deployment to be consumed with the [Canonical Observability Stack (COS)](https://charmhub.io/topics/canonical-observability-stack).
To do so, we will sync resources stored in a git repository to COS Lite.

### Prerequisites

Deploy the `cos-lite` bundle in a Kubernetes environment and integrate Charmed Apache Kafka to the COS offers, as shown in the [How to Enable Monitoring](how-to-monitoring-enable-monitoring) guide.
This guide will refer to the models that charms are deployed into as:

* `<cos-model>` for the model containing observability charms (and deployed on K8s)
* `<apps-model>` for the model containing Charmed Apache Kafka and optional charms
  (e.g. TLS certificate operators, `opentelemetry-collector`, and `data-integrator`).

### Create a repository with a custom monitoring setup

Create an empty git repository, or in an existing one, save your alert rules and dashboard models under the `<path_to_prom_rules>`, `<path_to_loki_rules>` and `<path_to_models>` folders.

If you want a primer to rule writing, refer to the [Prometheus documentation](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/).  
You may also find an example in the [`kafka-test-app` repository](https://github.com/canonical/kafka-test-app).

Then, push your changes to the remote repository.

### Deploy the COS configuration charm

Deploy the [COS configuration](https://charmhub.io/cos-configuration-k8s) charm in the `<cos-model>` model:

```shell
juju deploy cos-configuration-k8s cos-config \
  -m <cos-model> \
  --config git_repo=<repository_url> \
  --config git_branch=<branch>
```

The COS configuration charm keeps the monitoring stack in sync with our repository, by forwarding resources to Prometheus, Loki and Grafana.
Refer to the [documentation](https://charmhub.io/cos-configuration-k8s/configure) for all configuration options, including how to access a private repository.  
Adding, updating or deleting an alert rule or a dashboard in the repository will be reflected in the monitoring stack.

```{note}
You need to manually refresh `cos-config`'s local repository with the *sync-now* action if you do not want to wait for the next [update-status event](https://canonical.com/juju/docs/juju-cli/3.6/reference/hook/#update-status) to pull the latest changes.
```

### Forward the rules and dashboards

The path to the resource folders can be set after deployment:

```shell
juju config cos-config -m <cos-model> \
  prometheus_alert_rules_path=<path_to_prom_rules> \
  loki_alert_rules_path=<path_to_loki_rules> \
  grafana_dashboards_path=<path_to_models>
```

Then, integrate the charm to the COS operator to forward the rules and dashboards:

```shell
juju integrate cos-config prometheus -m <cos-model>
juju integrate cos-config grafana -m <cos-model>
juju integrate cos-config loki -m <cos-model>
```

After this is complete, the monitoring COS stack should be up, and ready to fire alerts based on our rules.
As for the dashboards, they should be available in the Grafana interface.

### Conclusion

In this guide, we enabled monitoring on a Charmed Apache Kafka deployment and integrated alert rules and dashboards by syncing a git repository to the COS stack.
