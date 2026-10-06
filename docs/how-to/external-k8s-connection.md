(how-to-external-k8s-connection)=
# External K8s connection

```{note}
This feature is available in charm revisions 69+. You can use the `edge` track to get the latest revision of the charm.
```

To make the Charmed Apache Kafka K8s brokers reachable from outside the Kubernetes cluster, the charm application can manage several NodePort services:

```shell
kubectl get services -n <model>
```

The result is a console output that looks like the following table:

```text
| NAME                             | TYPE      | CLUSTER-IP     | CLIENT-IP   | PORT(S)                                                                         |
|----------------------------------|-----------|----------------|-------------|---------------------------------------------------------------------------------|
| `kafka-k8s`                        | ClusterIP | `10.152.183.77`  |             | 65535/TCP                                                                       |
| `kafka-k8s-endpoints `             | ClusterIP | None           |             |                                                                                 |
| `kafka-k8s-bootstrap`              | NodePort  | `10.152.183.193` |             | 29092:31982/TCP,29093:31262/TCP,29094:30845/TCP,29095:30153/TCP,29096:32601/TCP |
| `kafka-k8s-0-sasl-plaintext-scram` | NodePort  | `10.152.183.78`  |             | 29092:31211/TCP                                                                 |
| `kafka-k8s-0-sasl-ssl-scram`       | NodePort  | `10.152.183.104` |             | 29093:32306/TCP                                                                 |
| `kafka-k8s-1-sasl-plaintext-scram` | NodePort  | `10.152.183.125` |             | 29092:31421/TCP                                                                 |
| `kafka-k8s-1-sasl-ssl-scram`       | NodePort  | `10.152.183.162` |             | 29093:31710/TCP                                                                 |
| `kafka-k8s-2-sasl-plaintext-scram` | NodePort  | `10.152.183.223` |             | 29092:31449/TCP                                                                 |
| `kafka-k8s-2-sasl-ssl-scram`       | NodePort  | `10.152.183.117` |             | 29093:30641/TCP                                                                 |
```

The `kafka-k8s-bootstrap` NodePort service exposes a selection of ports, with each one being associated with the supported security protocol + authentication mechanism. For additional reference on which port refers to which security protocol and authentication mechanism, please refer to [Charmed Apache Kafka K8s Documentation - Reference Listeners](reference-broker-listeners).

The remaining NodePort services each correspond to a specific unit-id, security protocol and authentication mechanism, with fixed Ports and randomly allocated NodePorts.

> **Note**: The `kafka-k8s` and `kafka-k8s-endpoints` ClusterIP services seen above are created for every Juju application by default as part of the StatefulSet they are associated with. These services are not relevant to users and can be safely ignored.

## Setting up NodePort services

By default, the `kafka-k8s-bootstrap` NodePort service will be created automatically, however the `NodeIP:NodePort` addresses will be initially unreachable.

To connect to Charmed Apache Kafka K8s use Kubernetes-external clients, the aforementioned services must be associated with individual listeners. To achieve this:

1. Instruct each broker unit to create its own individual NodePort services by setting the charm configuration option `expose-external` to equal `nodeport` on the Kafka K8s application (default value is `false`):

    ```shell
    juju config kafka-k8s expose_external=nodeport
    ```

2. Enable at least one listener using the appropriate relation endpoints:
    - Each combination of supported security protocol + authentication mechanism corresponds to a specific port number
    - For additional reference on how to enable various security protocols and authentication mechanisms, as well as their associated ports, see the [Charmed Apache Kafka K8s Documentation - Reference Listeners](reference-broker-listeners)

Once both conditions have been met, the Charmed Apache Kafka K8s application will expose the per-unit NodePort services. For example, see the table in the [previous section](#external-k8s-connection) for the `kafka-k8s-0-sasl-plaintext-scram` service.

## Client connections using the bootstrap service

A client can be configured to connect to the `kafka-k8s-bootstrap` service using a Kubernetes NodeIP, and desired NodePort.

To get NodeIPs:

```shell
kubectl get nodes -o wide -n model | awk -v OFS='\t\t' '{print $1, $6}'
```

```text
NAME        INTERNAL-IP
node-0      10.155.67.110
node-1      10.155.67.120
node-2      10.155.67.130
```

NodeIPs are different for each deployment as they are randomly allocated.
For the example from the [previous section](#external-k8s-connection), the bootstrap NodePorts are:

```shell
29092:31982/TCP,29093:31262/TCP,29094:30845/TCP,29095:30153/TCP,29096:32601/TCP
```

To connect an external client to the Kafka cluster, configure the client application's `bootstrap-servers` to use the NodeIP and NodePorts for the desired security protocol and authentication mechanism.

For example, let's say that a client wishes to connect to the Kafka cluster with the following configuration:
- Running on `node-0`, `node-1` and `node-2` from earlier
- With `SASL_PLAINTEXT` as the  security protocol
- With `SCRAM-SHA-512` as the authentication mechanism

In this example, the client should configure their `bootstrap-servers` to equal `10.155.67.110:31982,10.155.67.120:31982,10.155.67.130:31982`.
