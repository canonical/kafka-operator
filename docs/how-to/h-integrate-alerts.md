# Integrate customer alerting rules and dashboards

This guide shows you how to integrate an existing set of rules to your Charmed Kafka and Charmed Zookeeper deployment to be consumed with the [Canonical Observability Stack (COS)](https://charmhub.io/topics/canonical-observability-stack).
To do so, we will sync the alert rules stored in a git repo to COS Lite.

## Prerequisites

Refer to the [Enable Monitoring](/t/charmed-kafka-documentation-how-to-enable-monitoring/10283) guide to deploy the cos-lite bundle in a Kubernetes environment and relate the Charmed Kafka model to the COS offers.
The rest of this guide works on the assumption that two models are deployed: `cos` (on k8s) containing the cos-lite bundle and `kafka-dev` (on VM **TODO: adapt for k8s version**) containing 5 Zookeeper units and **2** Kafka.
If your configuration differs, you will have to adapt this guide's content to your deployment.

## Create a repo with alert rules

To keep things simple, we will illustrate this guide with a single alert rule that Prometheus will fire if our Kafka cluster does not achieve high availability.
If you want a primer to rule writing, refer to the [Prometheus documentation](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/).  
Create an empty git repository, and save the following rule under `prometheus/rules/config.rules.yml`.
Then, push your changes to the remote repository.

```yaml
groups:
- name: availability
  rules:
  - alert: High Availability Not Achieved
    expr: count(kafka_server_replicamanager_leadercount) < 3
    for: 30s
    labels:
      severity: page
    annotations:
      summary: The number of active brokers do not achieve high availability
```


## Forward the configuration to the COS bundle

We will deploy the [COS configuration](https://charmhub.io/cos-configuration-k8s) charm to sync our repo's files to the various COS operators, starting with Prometheus.
Deploy the charm in the `cos` model:

```shell
juju deploy cos-configuration-k8s cos-config \
  --config git_repo=<repository_url> \
  --config git_branch=main \
  --config prometheus_alert_rules_path=/prometheus/rules
```

Refer to the [documentation](https://charmhub.io/cos-configuration-k8s/configure) for all config options, including how to access a private repository.  
Then, relate the charm to the Prometheus operator:

```shell
juju relate cos-config prometheus
```

After this is complete, the monitoring COS stack should be up, and ready to fire alerts based on our rule.

To connect to the Prometheus web interface, follow the [Browse dashboards](https://charmhub.io/topics/canonical-observability-stack/tutorials/install-microk8s#heading--browse-dashboards) section of the MicroK8s “Getting started” guide.

```shell
juju run traefik/0 show-proxied-endpoints --format=yaml \
  | yq '."traefik/0".results."proxied-endpoints"' \
  | jq
```

You should obtain a URL for Prometheus in the form of `"http://10.66.236.72/cos-prometheus-0"`.
If you followed this guide to the letter, you should see an `High Availability Not Achieved` alert firing with the value "2".
If you want to observe how the monitoring stack keeps up with the deployment, add a unit to the Kafka cluster in the `kafka-dev` model to see the alert go from "firing" to "inactive".


The [COS configuration](https://charmhub.io/cos-configuration-k8s) charm keeps the monitoring stack in sync with our repo.
Adding, updating or deleting a rule in the repo will be reflected in the monitoring stack.

[Note]
You need to manually refresh `cos-config`'s local repo with the *sync-now* action if you do no want to wait for the next [update-status event]() to pull the latest changes.
[/Note]

## Apply those concepts to a dashboard

As before, this guide will use the simplest dashboard possible to demonstrate how to integrate an existing Grafana dashboard to our COS stack. We will use the following dashboard model in our previous git repository.

<details><summary>Expand to see model</summary>

```json
{
  "annotations": {
    "list": [
      {
        "builtIn": 1,
        "datasource": {
          "type": "grafana",
          "uid": "-- Grafana --"
        },
        "enable": true,
        "hide": true,
        "iconColor": "rgba(0, 211, 255, 1)",
        "name": "Annotations & Alerts",
        "type": "dashboard"
      }
    ]
  },
  "editable": true,
  "fiscalYearStartMonth": 0,
  "graphTooltip": 0,
  "id": 10,
  "links": [],
  "liveNow": false,
  "panels": [
    {
      "datasource": {
        "type": "prometheus",
        "uid": "${prometheusds}"
      },
      "fieldConfig": {
        "defaults": {
          "mappings": [],
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "red",
                "value": null
              },
              {
                "color": "green",
                "value": 3
              }
            ]
          },
          "unit": "short"
        },
        "overrides": []
      },
      "gridPos": {
        "h": 7,
        "w": 9,
        "x": 0,
        "y": 0
      },
      "id": 1,
      "options": {
        "colorMode": "background",
        "graphMode": "none",
        "justifyMode": "auto",
        "orientation": "auto",
        "reduceOptions": {
          "calcs": [
            "lastNotNull"
          ],
          "fields": "",
          "values": false
        },
        "textMode": "auto"
      },
      "pluginVersion": "9.5.3",
      "targets": [
        {
          "datasource": {
            "type": "prometheus",
            "uid": "${prometheusds}"
          },
          "editorMode": "code",
          "expr": "count(kafka_server_replicamanager_leadercount)",
          "legendFormat": "__auto",
          "range": true,
          "refId": "A"
        }
      ],
      "title": "# Number of active brokers",
      "type": "stat"
    }
  ],
  "refresh": "",
  "schemaVersion": 38,
  "style": "dark",
  "tags": [],
  "templating": {
    "list": []
  },
  "time": {
    "from": "now-6h",
    "to": "now"
  },
  "timepicker": {},
  "timezone": "",
  "title": "Kafka cluster",
  "uid": "d05ae829-3279-4af5-99df-de8b9b32fc10",
  "version": 3,
  "weekStart": ""
}
```

</details>

Save this model under `grafana/dashboards/kafka_cluster.json`, and push your changes to the remote repo.
Then, switch to the `cos` model if needed and specify the path to the dashboard with the corresponding configuration option:

```
juju config cos-config grafana_dashboards_path=grafana/dashboards
```

Finally, relate the charm to Grafana:

```
juju relate cos-config grafana
```


To connect to the Grafana web interface, follow once again the [Browse dashboards](https://charmhub.io/topics/canonical-observability-stack/tutorials/install-microk8s#heading--browse-dashboards) section of the MicroK8s “Getting started” guide or the [Enable Monitoring](/t/charmed-kafka-documentation-how-to-enable-monitoring/10283) guide.

You should find your new "Kafka cluster" dashboard listed in Grafana.
Accessing it will display a panel with the number of active Kafka brokers in the cluster.

## Conclusion

In this guide, we enabled monitoring on a Kafka deployment and integrated an alert rule and a dashboard by syncing a git repository to the COS stack.
