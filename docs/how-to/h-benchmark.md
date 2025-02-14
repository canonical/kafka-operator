# How to benchmark Charmed Apache Kafka

The Apache Kafka benchmark charm uses the OpenMessaging tool to test both producer and consumer performance in the cluster.

The OpenMessaging allows for a distributed deployment, where the charm leader will run the main "manager" process and gather the metrics, whilst other units will act as followers and act as producer/consumers of the cluster.

## Deploy

Apache Kafka benchmark charm can be connected with either the [Charmed Apacke Kafka](https://canonical.com/data/docs/kafka/iaas) or the [Charmed Apache Kafka K8s](https://canonical.com/data/docs/kafka/k8s).

### Apache Kafka setup

Deploy the apropriate charmed operator for the [type of your Juju cloud environment](https://canonical-juju.readthedocs-hosted.com/en/latest/user/reference/cloud/#machine-clouds-vs-kubernetes-clouds):

* For Machine clouds, see the [How to deploy guide for Charmed Apache Kafka](https://canonical.com/data/docs/kafka/iaas/h-deploy).
* For Kubernetes clouds, see the [How to deploy guide for Charmed Apache Kafka K8s](https://canonical.com/data/docs/kafka/k8s/t-deploy). Since the benchmark charm is for machine clouds only, the Apache Kafka cluster must be deployed on a different (Kubernetes) environment. Hence, it must be configured to [expose its client endpoints via NodePort](https://canonical.com/data/docs/kafka/k8s/h-external-k8s-connection).

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

Charmed Apache Kafka supports TLS provider integration as described for both [machine](https://canonical.com/data/docs/kafka/iaas/h-enable-encryption) and [k8s](https://canonical.com/data/docs/kafka/k8s/h-enable-encryption) charmed operators.

The Apache Kafka Benchmark can be then related to a TLS operator, such as [self-signed-certificates](https://charmhub.io/self-signed-certificates), for example:

```
juju deploy self-signed-certificates
juju integrate kafka-benchmark self-signed-certificates
```

## Run the benchmark

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

## Get the Results

Kafka benchmark charm updates its metrics to COS and can be found under `openmessaging_` metric on prometheus:

![Screenshot from 2025-02-14 11-02-47](https://github.com/user-attachments/assets/b9da658c-1d76-4f2b-9cbc-f4243123cb34)
