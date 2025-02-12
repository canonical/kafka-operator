# How to benchmark Charmed Apache Kafka
The Apache Kafka benchmark charm uses the OpenMessaging tool to test both producer and consumer performance in the cluster.

The OpenMessaging allows for a distributed deployment, where the charm leader will run the main "manager" process and gather the metrics, whilst other units will act as followers and act as producer/consumers of the cluster.

## Deploy
Create a new Juju model:
```
juju add-model kafka-benchmark
Deploy Apache Kafka with Juju:

juju deploy kafka --channel=3/edge
juju deploy zookeeper --channel=3/edge
juju relate kafka zookeeper
```
Deploy the benchmark tool and relate it to the cluster:
```
juju deploy kafka-benchmark --channel=latest/edge
juju relate kafka kafka-benchmark
```

### Integrate with COS
The benchmark charm needs COS to collect metrics during the test. Relate the Apache Kafka benchmark with a [grafana-agent operator](https://charmhub.io/grafana-agent).

For more details on how to deploy and configure COS and its agents, check [the upstream documentation](https://canonical.com/data/docs/kafka/iaas/h-enable-monitoring).

Once the grafana-agent is deployed, relate it with:
```
juju relate grafana-agent kafka-benchmark
```
The benchmark data will be collected every 10s and sent to prometheus.

## Run the Benchmark
To kick start a benchmark, execute the following actions:
```
juju run kafka-benchmark/leader prepare  # to set the environment and the cluster
juju run kafka-benchmark/leader run
```

The units will pick-up the command and start executing the benchmark.

### Stop the Benchmark
To stop the benchmark, execute:
```
juju run kafka-benchmark/leader stop
```
Optionally, it is possible to clean the current benchmark data using:
```
juju run kafka-benchmark/leader cleanup
```
That will return the Apache Kafka benchmark charm to its original condition.
