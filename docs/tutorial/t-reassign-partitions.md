This is part of the Charmed Kafka Tutorial. Please refer to the [overview page](/t/charmed-kafka-documentation-tutorial-overview/10571) for more information and the overview of the content.

## Partition rebalancing and reassignment

By default, when scaling-out a Kafka cluster, partitions allocated to the original brokers are not reallocated to make use of any new storage volumes and brokers, which can result in over-provisioning of resources. The inverse is also true when scaling-in, which can result in under-replicated partitions at best, and permanent data loss at worst.

To address this, we can make use of [LinkedIn's Cruise Control](https://github.com/linkedin/cruise-control), which is bundled as part of the Charmed Kafka [Snap](https://github.com/canonical/charmed-kafka-snap) and [rock](https://github.com/canonical/charmed-kafka-rock).

At a high level, Cruise Control is made up of the following five components:

- **Workload Monitor** - responsible for the metrics collection from Kafka
- **Analyzer** - generates allocation proposals based on configured [Goals](https://github.com/linkedin/cruise-control?tab=readme-ov-file#goals)
- **Anomaly Detector** - detects failures in brokers, disks, metrics or goals and (optionally) self-heals
- **Webserver** - a REST API for user operations
- **Executor** - issues re-allocation commands to Kafka

### Deploying partition balancer

The Charmed Kafka charms have a configuration option `roles`, which takes a list of possible values.
Different roles can be configured to run on the same machine, or as separate Juju applications.

The two necessary roles for cluster rebalancing are:
- `broker` - running Apache Kafka
- `balancer` - running Cruise Control

> **Note**: It is recommended to deploy a separate Juju application for running Cruise Control in production environments.

For the purposes of this tutorial, we will be deploying a single Charmed Kafka unit to serve as the `balancer`:

```shell
juju deploy kafka --config roles=balancer -n 1 cruise-control
```

Earlier in the tutorial, we covered enabling TLS encryption, so we will repeat that step here for the new `cruise-control` application:

```shell
juju relate cruise-control:certificates self-signed-certificates
```

Now, to make the new `cruise-control` application aware of the existing Kafka cluster, we will relate the two applications using the `peer_cluster` relation interface, ensuring that the `broker` cluster is using the `peer-cluster` relation-endpoint, and the `balancer` cluster is using the `peer-cluster-orchestrator` relation-endpoint:

```shell
juju relate kafka:peer-cluster-orchestrator cruise-control:peer-cluster
```

### Adding new brokers

Let's assume that we have three `kafka` units already, and have an active client application writing messages to an existing topic (as per the [Relate applications tutorial page](/t/charmed-kafka-tutorial-relate-apache-kafka/10573) earlier). Let's scale the `kafka` application out to four units:

```shell
juju add-unit kafka 4
```

We can see that, by default, no partitions are allocated by checking the log directory assignment for the new unit `3`:

```bash
juju ssh kafka/leader sudo -i \
    'charmed-kafka.log-dirs' \
    '--describe' \
    '--bootstrap-server localhost:9093' \
    '--command-config /var/snap/charmed-kafka/current/etc/kafka/client.properties' \
    | tail -n +3 | jq -c '.brokers[] | select(.broker == 3)' | jq
```

This should produce output similar to the result seen below, with no partitions allocated by default:

```json
{
  "broker": 3,
  "logDirs": [
    {
      "error": null,
      "logDir": "/var/snap/charmed-kafka/common/var/lib/kafka/data",
      "partitions": []
    }
  ]
}
```

Now, to rebalance some existing partitions from brokers `0`, `1` and `2`, let's allocate them to broker `3`:

```shell
juju run cruise-control/0 rebalance mode=add brokerid=3 --wait=2m
```

> **NOTE** - If this action fails with a message similar to `Cruise Control balancer service has not yet collected enough data to provide a partition reallocation proposal`, wait 20 minutes or so and try again. Cruise Control takes a while to collect sufficient metrics from the Kafka cluster during a cold deployment

By default, the `rebalance` action runs as a 'dryrun', where the returned result is what **would** happen were the partition rebalance actually executed. In the action result, one can find some rich information on the proposed allocation. 

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

```shell
juju run cruise-control/0 rebalance mode=add dryrun=false brokerid=3 --wait=10m
```

Partition rebalances can take quite some time. To monitor the progress, in a separate terminal session, you can check the Juju debug logs to see it in progress:

```
unit-cruise-control-0: 22:18:41 INFO unit.cruise-control/0.juju-log Waiting for task execution to finish for user_task_id='d3e426a3-6c2e-412e-804c-8a677f2678af'...
unit-cruise-control-0: 22:18:51 INFO unit.cruise-control/0.juju-log Waiting for task execution to finish for user_task_id='d3e426a3-6c2e-412e-804c-8a677f2678af'...
unit-cruise-control-0: 22:19:02 INFO unit.cruise-control/0.juju-log Waiting for task execution to finish for user_task_id='d3e426a3-6c2e-412e-804c-8a677f2678af'...
unit-cruise-control-0: 22:19:12 INFO unit.cruise-control/0.juju-log Waiting for task execution to finish for user_task_id='d3e426a3-6c2e-412e-804c-8a677f2678af'...
...
```

Once it has been completed, and the action has returned a result, you can now verify the partition movement using the same commands as before:

```bash
juju ssh kafka/leader sudo -i \
    'charmed-kafka.log-dirs' \
    '--describe' \
    '--bootstrap-server localhost:9093' \
    '--command-config /var/snap/charmed-kafka/current/etc/kafka/client.properties' \
    | tail -n +3 | jq -c '.brokers[] | select(.broker == 3)' | jq
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
        ...
```

### Removing old brokers

Following on from the previous example of `Adding new brokers`, let's proceed to safely remove the new broker unit. Before scaling down the Juju application, we must make sure to carefully move any existing data from units about to be removed, to another unit.

In practice, this means running a `rebalance` Juju action as seen above, **BEFORE** scaling down the application. This ensures that data is moved, prior to the unit becoming unreachable and permanently losing the data on it.

> **NOTE**: As partition data is replicated across a finite number of units based on the value of the Kafka cluster's `replication.factor` property (default value is `3`), it is imperative to remove only one broker at a time, so as to avoid losing all available replicas for a given partition.

To remove the most recent broker unit `3` from the previous example, re-run the action with a new parameter value of `mode=remove`:

```shell
juju run cruise-control/0 rebalance mode=remove dryrun=false brokerid=3 --wait=10m
```

This does not remove the unit, but moves the partitions from the broker on unit number `3` to other brokers within the cluster.

Once the action has been completed, we can verify that broker `3` no longer has any assigned partitions by doing the following:

```bash
juju ssh kafka/leader sudo -i \
    'charmed-kafka.log-dirs' \
    '--describe' \
    '--bootstrap-server localhost:9093' \
    '--command-config /var/snap/charmed-kafka/current/etc/kafka/client.properties' \
    | tail -n +3 | jq -c '.brokers[] | select(.broker == 3)' | jq
```

This should result something similar to the result seen below, with broker `3` now having no partitions assigned, completing the safe reassignment of a broker's data to other brokers in the cluster

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

Now, it is safe to scale-in the cluster, removing broker number `3`:

```shell
juju remove-unit kafka/3
```

### Full cluster rebalancing

If a cluster has been running in production for some time, partition allocations may be imbalanced. This can happen naturally as topic load varies, topics are reconfigured to have more/less partitions, or new topics are added/removed etc. As such, it is expected that periodically during the lifetime of a deployment, an administrator will need to redistribute the partition allocation across the existing broker units as part of cluster maintenance.

Unlike `Adding new brokers` or `Removing old brokers`, this includes a full re-shuffle of partition allocation across all currently live broker units.

To achieve this, re-run the action with a new parameter value of `mode=full`. Let's try it with a `dryrun` (by default) for now:

```shell
juju run cruise-control/0 rebalance mode=full --wait=10m
```

Looking at the bottom of the output, we can see the value of the `balancedness` score before and after the proposed 'full' rebalance:

```
summary:
  ...
  ondemandbalancednessscoreafter: "90.06926434109423"
  ondemandbalancednessscorebefore: "85.15942156660185"
  ...
```

To implement the proposed changes, run:

```shell
juju run cruise-control/0 rebalance mode=full dryrun=false --wait=10m
```

