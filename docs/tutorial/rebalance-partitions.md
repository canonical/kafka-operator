(tutorial-rebalance-partitions)=
# 6. Rebalance and reassign partitions

This is part of the [Charmed Apache Kafka K8s Tutorial](index.md).

By default, when adding more brokers to an Apache Kafka cluster, the current allocated partitions on the original brokers are not automatically redistributed across the new brokers. This can lead to inefficient resource usage and over-provisioning. On the other hand, when removing brokers to reduce capacity, partitions assigned to the removed brokers are also not redistributed, which can result in under-replicated data at best and permanent data loss at worst.

To address this, we can make use of [LinkedIn's Cruise Control](https://github.com/linkedin/cruise-control), which is bundled as part of the Charmed Apache Kafka [snap](https://github.com/canonical/charmed-kafka-snap) and [rock](https://github.com/canonical/charmed-kafka-rock).

At a high level, Cruise Control is made up of the following five components:

- **Workload Monitor** - responsible for the metrics collection from Apache Kafka
- **Analyser** - generates allocation proposals based on configured [Goals](https://github.com/linkedin/cruise-control?tab=readme-ov-file#goals)
- **Anomaly Detector** - detects failures in brokers, disks, metrics or goals and (optionally) self-heals
- **Web server** - a REST API for user operations
- **Executor** - issues re-allocation commands to Apache Kafka

## Deploying partition balancer

The Charmed Apache Kafka K8s charm has a configuration option `roles`, which takes a list of possible values.
Different roles can be configured to run on the same machine, or as separate Juju applications.

The two necessary roles for cluster rebalancing are:

- `broker` - running Apache Kafka
- `balancer` - running Cruise Control

```{note}
It is recommended to deploy a separate Juju application for running Cruise Control in production environments.
```

For the purposes of this tutorial, we will be deploying a single Charmed Apache Kafka K8s unit to serve as the `balancer`:

```bash
juju deploy kafka-k8s --trust --config roles=balancer -n 1 cruise-control
```

Earlier in the tutorial, we covered enabling TLS encryption, so we will repeat that step here for the new `cruise-control` application:

```bash
juju integrate cruise-control:certificates self-signed-certificates
```

Now, to make the new `cruise-control` application aware of the existing Apache Kafka cluster, we will integrate the two applications using the `peer_cluster` relation interface, ensuring that the `broker` cluster is using the `peer-cluster` relation-endpoint, and the `balancer` cluster is using the `peer-cluster-orchestrator` relation-endpoint:

```bash
juju integrate kafka-k8s:peer-cluster-orchestrator cruise-control:peer-cluster
```

## Adding new brokers

After completing the steps in the [Integrate with client applications](tutorial-integrate-with-client-applications) tutorial page, you should have three `kafka` units and a client application actively writing messages to an existing topic. Let's scale-out the `kafka` application to four units:

```bash
juju scale-application kafka-k8s 4
```

By default, no partitions are allocated for the new unit `3`. You can see that by checking the log directory assignment:

```bash
juju ssh --container kafka kafka-k8s/leader \
    '/opt/kafka/bin/kafka-log-dirs.sh' \
    '--describe' \
    '--bootstrap-server <unit-ip>:9093' \
    '--command-config /etc/kafka/client.properties' \
    '2> /dev/null' \
    | tail -n +1 | jq -c '.brokers[] | select(.broker == 3)' | jq
```

This should produce output similar to the result seen below, with no partitions allocated by default:

```json
{
  "broker": 3,
  "logDirs": [
    {
      "error": null,
      "logDir": "/var/lib/kafka/data",
      "partitions": []
    }
  ]
}
```

Now, let's run the `rebalance` action to allocate some existing partitions from brokers `0`, `1` and `2` to broker `3`:

```bash
juju run cruise-control/0 rebalance mode=add brokerid=3 --wait=2m
```

```{note}
If this action fails with a message similar to `Cruise Control balancer service has not yet collected enough data to provide a partition reallocation proposal`, wait 20 minutes or so and try again. Cruise Control takes a while to collect sufficient metrics from an Apache Kafka cluster during a cold deployment.
```

By default, the `rebalance` action runs as a "dryrun", where the returned result is what **would** happen were the partition rebalance actually executed. The action output has detailed information on the proposed allocation.

For example, the **summary** section might look similar to this:

```yaml
summary:
  datatomovemb: "0"
  excludedbrokersforleadership: '[]'
  excludedbrokersforreplicamove: '[]'
  excludedtopics: '[]'
  intrabrokerdatatomovemb: "0"
  monitoredpartitionspercentage: "100.0"
  numintrabrokerreplicamovements: "0"
  numleadermovements: "0"
  numreplicamovements: "76"
  ondemandbalancednessscoreafter: "78.8683072916115"
  ondemandbalancednessscorebefore: "68.01755475998335"
  provisionrecommendation: ""
  provisionstatus: RIGHT_SIZED
  recentwindows: "1"
```

If we are happy with this proposal, we can re-run the action, but this time instructing the charm to actually execute the proposal:

```bash
juju run cruise-control/0 rebalance mode=add dryrun=false brokerid=3 --wait=10m
```

Partition rebalances can take quite some time. To monitor the progress, in a separate terminal session, check the Juju debug logs to see it in progress:

```text
unit-cruise-control-0: 22:18:41 INFO unit.cruise-control/0.juju-log Waiting for task execution to finish for user_task_id='d3e426a3-6c2e-412e-804c-8a677f2678af'...
unit-cruise-control-0: 22:18:51 INFO unit.cruise-control/0.juju-log Waiting for task execution to finish for user_task_id='d3e426a3-6c2e-412e-804c-8a677f2678af'...
unit-cruise-control-0: 22:19:02 INFO unit.cruise-control/0.juju-log Waiting for task execution to finish for user_task_id='d3e426a3-6c2e-412e-804c-8a677f2678af'...
unit-cruise-control-0: 22:19:12 INFO unit.cruise-control/0.juju-log Waiting for task execution to finish for user_task_id='d3e426a3-6c2e-412e-804c-8a677f2678af'...
...
```

Once the action is complete, verify the partitions using the same commands as before:

```bash
juju ssh --container kafka kafka-k8s/leader \
    '/opt/kafka/bin/kafka-log-dirs.sh' \
    '--describe' \
    '--bootstrap-server <unit-ip>:9093' \
    '--command-config /etc/kafka/client.properties' \
    '2> /dev/null' \
    | tail -n +1 | jq -c '.brokers[] | select(.broker == 3)' | jq
```

This should produce an output similar to the result seen below, with broker `3` now having assigned partitions present, completing the adding of a new broker to the cluster:

```json
{
  "broker": 3,
  "logDirs": [
    {
      "partitions": [
        {
          "partition": "__KafkaCruise ControlModelTrainingSamples-10",
          "size": 0,
          "offsetLag": 0,
          "isFuture": false
        },
        
      ]
    }
  ]
}
```

## Removing old brokers

To safely scale-in an Apache Kafka cluster, we must make sure to carefully move any existing data from units about to be removed, to another unit that will persist.

In practice, this means running a `rebalance` Juju action as seen above, **BEFORE** scaling down the application. This ensures that data is moved, prior to the unit becoming unreachable and permanently losing the data on it.

```{note}
As partition data is replicated across a finite number of units based on the value of the Apache Kafka cluster's `replication.factor` property (default value is `3`), it is imperative to remove only one broker at a time, to avoid losing all available replicas for a given partition.
```

To remove the most recent broker unit `3` from the previous example, re-run the `rebalance` action with `mode=remove`:

```bash
juju run cruise-control/0 rebalance mode=remove dryrun=false brokerid=3 --wait=10m
```

This does not remove the unit, but moves the partitions from the broker on unit number `3` to other brokers within the cluster.

Once the action has been completed, verify that broker `3` no longer has any assigned partitions:

```bash
juju ssh --container kafka kafka-k8s/leader \
    '/opt/kafka/bin/kafka-log-dirs.sh' \
    '--describe' \
    '--bootstrap-server <unit-ip>:9093' \
    '--command-config /etc/kafka/client.properties' \
    '2> /dev/null' \
    | tail -n +1 | jq -c '.brokers[] | select(.broker == 3)' | jq
```

Make sure that broker `3` now has no partitions assigned, for example:

```json
{
  "broker": 3,
  "logDirs": [
    {
      "partitions": [],
      "error": null,
      "logDir": "/var/lib/kafka/data"
    }
  ]
}
```

Now, it is safe to scale-in the cluster, removing the broker number `3` completely:

```bash
juju scale-application kafka-k8s 3
```

## Full cluster rebalancing

Over time, an Apache Kafka cluster in production may develop an imbalance in partition allocation, with some brokers having greater/fewer allocated than others. This can occur as topic load fluctuates, partitions are added or removed due to reconfiguration, or new topics are created or deleted. Therefore, as part of regular cluster maintenance, administrators should periodically redistribute partitions across existing broker units to ensure optimal performance.

Unlike `Adding new brokers` or `Removing old brokers`, this includes a full re-shuffle of partition allocation across all currently live broker units.

To achieve this, re-run the `rebalance` action with the `mode=full`. You can do it in the "dryrun" mode (by default) for now:

```bash
juju run cruise-control/0 rebalance mode=full --wait=10m
```

Looking at the bottom of the output, see the value of the `balancedness` score before and after the proposed 'full' rebalance:

```text
summary:
  ...
  ondemandbalancednessscoreafter: "90.06926434109423"
  ondemandbalancednessscorebefore: "85.15942156660185"
  ...
```

To implement the proposed changes, run the same command but with `dryrun=false`:

```bash
juju run cruise-control/0 rebalance mode=full dryrun=false --wait=10m
```
