---
myst:
  html_meta:
    description: "Configure NodePort services for clients outside a Charmed Apache Kafka K8s cluster."
---

(how-to-external-k8s-connection)=
# How to connect to Charmed Apache Kafka K8s externally

```{note}
This page applies to the K8s charm on the 4.x track only. VM client access is
covered in [How to manage client connections](how-to-client-connections).
```

By default, the K8s charm exposes client listeners only inside the Kubernetes
cluster. It can create a bootstrap NodePort service and one NodePort service per
broker so clients outside the cluster can use the broker addresses returned by
Apache Kafka.

## Enable the NodePort services

Configure the broker application:

```shell
juju config kafka-k8s expose-external=nodeport
```

At least one client listener must also be active. Integrate a client through
`kafka-client`; add `certificates`, `client-cas`, or `oauth` as required for the
chosen authentication and encryption mode. See the [listeners
reference](reference-broker-listeners).

Inspect the resulting Services in the Juju model namespace:

```shell
kubectl get services -n <model>
```

The charm creates `kafka-k8s-bootstrap` and per-unit Services whose names include
the unit ID, protocol, and authentication mechanism. Kubernetes allocates the
NodePort values, so discover them from the Service rather than assuming a fixed
NodePort:

```shell
kubectl get service kafka-k8s-bootstrap -n <model>
```

The service ports identify the protocol before translation to a NodePort:

| Service port | Protocol and authentication |
|---:|---|
| `29092` | SASL_PLAINTEXT with SCRAM-SHA-512 |
| `29093` | SASL_SSL with SCRAM-SHA-512 |
| `29094` | SSL with mTLS |
| `29095` | SASL_PLAINTEXT with OAuth |
| `29096` | SASL_SSL with OAuth |

The ordinary `kafka-k8s` and `kafka-k8s-endpoints` ClusterIP Services are part of
the application's StatefulSet networking and are not external entry points.

## Configure the client

Retrieve the Kubernetes node IP addresses:

```shell
kubectl get nodes -o wide | awk -v OFS='\t\t' '{print $1, $6}'
```

Example output:

```text
NAME        INTERNAL-IP
node-0      10.155.67.110
node-1      10.155.67.120
node-2      10.155.67.130
```

Map the desired service port to its allocated NodePort. For example:

```shell
kubectl get service kafka-k8s-bootstrap -n <model> \
  -o jsonpath='{range .spec.ports[*]}{.port}{" -> "}{.nodePort}{"\n"}{end}'
```

Configure the client's `bootstrap.servers` with reachable node IPs and the
NodePort for the selected protocol. If service port `29092` maps to NodePort
`31982`, for example:

```text
10.155.67.110:31982,10.155.67.120:31982,10.155.67.130:31982
```

```{note}
The charm creates the NodePort Services with `externalTrafficPolicy=Local`:
traffic is only forwarded to nodes that run a Kafka broker pod. Prefer node IPs
that host broker units, and verify each node you list actually forwards
connections. Also note that each broker advertises its own per-broker NodePort
Service, so clients must be able to reach **all** advertised broker endpoints,
not only the bootstrap address.
```

Whether node IPs are reachable and which firewall rules apply depends on the
Kubernetes provider. On managed clouds, allow the selected NodePort range only
from trusted client networks.
