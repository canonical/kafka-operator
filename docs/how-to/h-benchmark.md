# How to benchmark Charmed Apache Kafka

The Apache Kafka benchmark charm uses the OpenMessaging tool to test both producer and consumer performance in the cluster.

The OpenMessaging allows for a distributed deployment, where the charm leader will run the main "manager" process and gather the metrics, whilst other units will act as followers and act as producer/consumers of the cluster.

## Deploy

Apache Kafka benchmark charm can be connected with either the [Charmed Apacke Kafka](https://canonical.com/data/docs/kafka/iaas) or the [Charmed Apache Kafka K8s](https://canonical.com/data/docs/kafka/k8s).

### Apache Kafka setup

#### Baremetal or Virtual Machines

Deploy Charmed Apache Kafka following the instructions in its [deployment guide](https://canonical.com/data/docs/kafka/iaas/h-deploy)

#### Kubernetes

Deploy Charmed Apache Kafka following the instructions in its [deployment guide](https://canonical.com/data/docs/kafka/k8s/t-deploy).

The Apache Kafka cluster must be configured to expose its client endpoints via NodePort, [æs described here](https://canonical.com/data/docs/kafka/k8s/h-external-k8s-connection).

### Benchmark Deployment

Add the Apache Kafka benchmark charm using:

```
juju deploy kafka-benchmark --channel=latest/edge
juju relate kafka kafka-benchmark
```

### Integrate with COS

The benchmark charm needs a [COS](https://charmhub.io/topics/canonical-observability-stack) deployment running on a separate Juju model in Kubernetes to collect metrics during the test. Relate the Apache Kafka benchmark with a [grafana-agent operator](https://charmhub.io/grafana-agent).

For instructions on how to deploy and configure COS and its agents, see the [How to enable monitoring](https://canonical.com/data/docs/kafka/iaas/h-enable-monitoring) guide.

Once the grafana-agent is deployed, relate it with:

```
juju relate grafana-agent kafka-benchmark
```

The benchmark data will be collected every 10s and sent to prometheus.

### Integrate with TLS

Optionally, the entire deployment can use TLS.

Charmed Apache Kafka supports TLS integration and described for both [baremetal / virtual machines](https://canonical.com/data/docs/kafka/k8s/t-enable-encryption) or [k8s](https://canonical.com/data/docs/kafka/iaas/h-enable-encryption) operators.

The Apache Kafka Benchmark can be then related to a TLS operator, such as [self-signed-certificates](https://charmhub.io/self-signed-certificates), for example:

```
juju integrate kafka-benchmark self-signed-certificates
```

## Start the Benchmark

### Prepare

The first step is to prepare the benchmark fleet with:

```
juju run kafka-benchmark/leader prepare
```

### Run

The next command is `run`, to start the benchmark charms to produce and consume data.

```
juju run kafka-benchmark/leader run
```

The units will pick-up the command and start executing the benchmark.

### Stop

To stop the benchmark, execute:

```
juju run kafka-benchmark/leader stop
```

Optionally, it is possible to clean the current benchmark data using:

### Clean-up

To return the cluster to its original state, run:

```
juju run kafka-benchmark/leader cleanup
```

