# How to benchmark Charmed Apache Kafka

The Apache Kafka benchmark charm uses the OpenMessaging tool to test both producer and consumer performance in the cluster.

The OpenMessaging allows for a distributed deployment, where the charm leader will run the main "manager" process and gather the metrics, whilst other units will act as followers and act as producer/consumers of the cluster.

## Deploy

Apache Kafka benchmark charm can be connected with either the [Charmed Apacke Kafka](https://canonical.com/data/docs/kafka/iaas) or the [Charmed Apache Kafka K8s](https://canonical.com/data/docs/kafka/k8s).

### Apache Kafka setup

Deploy the apropriate charmed operator for the [type of your Juju cloud environment](https://canonical-juju.readthedocs-hosted.com/en/latest/user/reference/cloud/#machine-clouds-vs-kubernetes-clouds):

* For Machine clouds, see the [How to deploy guide for Charmed Apache Kafka](https://canonical.com/data/docs/kafka/iaas/h-deploy).
* For Kubernetes clouds, see the [How to deploy guide for Charmed Apache Kafka K8s](https://canonical.com/data/docs/kafka/k8s/t-deploy). Since the benchmark charm is for machine clouds only, the Apache Kafka cluster must be deployed on a different (Kubernetes) environment. Hence, it must be configured to [expose its client endpoints via NodePort](https://canonical.com/data/docs/kafka/k8s/h-external-k8s-connection).

### Benchmark deployment

The Apache Kafka benchmark runs several producers and consumers for the same topic with the right number of partitions to enable parallelism. The total number of parallel workers is equal to the **number of [units](https://canonical-juju.readthedocs-hosted.com/en/latest/user/reference/unit/)** for the benchmark application multiplied by the **number of workers on each unit**. The number of workers per unit is set by the `parallel_processes` parameter. 

The workers are distributed equally between producers and consumers. Hence, the Apache Kafka benchmark needs at least two workers in total. That minimal configuration can be achieved by having two workers on the same single unit or two units with one worker on each. 

Deploy the benchmark charm with the desired number of units and workers per unit.
For example, to deploy two units with one worker (either a consumer or a producer) on each, run:

```
juju deploy kafka-benchmark --channel=latest/edge -n2 --config parallel_processes=1
```

Each unit must have at least 4 GB of RAM available for each running worker.

Once the benchmark charm is deployed and ready, integrate it with the Apache Kafka cluster:

```
juju integrate kafka kafka-benchmark
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

Charmed Apache Kafka supports TLS provider integration as described for both [machine](https://canonical.com/data/docs/kafka/iaas/h-enable-encryption) and [k8s](https://canonical.com/data/docs/kafka/k8s/h-enable-encryption) charmed operators, such as [self-signed-certificates](https://charmhub.io/self-signed-certificates), for example:

```
juju deploy self-signed-certificates
juju integrate kafka-benchmark self-signed-certificates
```

## Run the benchmark

Now that the benchmark charm is deployed to all intended units, we can adjust benchmarking parameters and control the whole cluster by using the charm's actions on the leader unit.

You can adjust benchmarking parameters with the `juju config` command:

```
juju config kafka-benchmark run_count=3
```

For all configuration options, see the [Configurations](https://charmhub.io/kafka-benchmark/configurations).

### Prepare

The first step is to prepare the benchmark fleet with:

```
juju run kafka-benchmark/leader prepare
```

### Start

Use the `run` action, to start benchmarking (to produce and consume data):

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

## Get the results

Kafka benchmark charm updates its metrics to COS and can be found under `openmessaging_` metric on prometheus:

![Prometheus results example](https://github.com/user-attachments/assets/b9da658c-1d76-4f2b-9cbc-f4243123cb34)
