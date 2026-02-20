---
myst:
  html_meta:
    description: "Rebalance Charmed Apache Kafka partitions using Cruise Control - optimize resource distribution when scaling brokers."
---

(tutorial-rebalance-partitions)=
# 7. Rebalance and reassign partitions

This is a part of the [Charmed Apache Kafka Tutorial](index.md).

By default, when adding more brokers to a Charmed Apache Kafka cluster, the current
allocated partitions on the original brokers are not automatically redistributed across
the new brokers. This can lead to inefficient resource usage and over-provisioning.
On the other hand, when removing brokers to reduce capacity, partitions assigned
to the removed brokers are also not redistributed, which can result in under-replicated data
at best and permanent data loss at worst.

To address this, we can make use of
[LinkedIn's Cruise Control](https://github.com/linkedin/cruise-control), which is bundled as part
of the Charmed Apache Kafka [snap](https://github.com/canonical/charmed-kafka-snap)
and [rock](https://github.com/canonical/charmed-kafka-rock).

<!-- At a high level, Cruise Control is made up of the following five components:

- **Workload Monitor** - responsible for the metrics collection from Charmed Apache Kafka
- **Analyser** - generates allocation proposals based on configured [Goals](https://github.com/linkedin/cruise-control?tab=readme-ov-file#goals)
- **Anomaly Detector** - detects failures in brokers, disks, metrics or goals and (optionally) self-heals
- **Web server** - a REST API for user operations
- **Executor** - issues re-allocation commands to Apache Kafka -->

The Charmed Apache Kafka charm has a configuration option `roles`, which takes
a list of possible values. Different roles can be configured to run on the same machine,
or as separate Juju applications.

The `balancer` role is required to run the Cruise Control.
We will need to add this role to one of the existing Juju applications:
either `kafka` with the `broker` role, or `kraft` with the `controller` role.

We recommend combining `controller` and `balancer` role together on the `kraft` application,
due to higher performance demands of the `broker` role.

## Setup

Let's add the role `balancer` to the existing `kraft` Juju application:

```shell
juju config kraft roles=balancer,controller
```

Wait for the status to become `active`/`idle`:

```shell
watch juju status --color
```

## Adding new brokers

Let's scale-out the `kafka` application to four units (add one more):

```bash
juju add-unit kafka
```

Wait for the additional unit to be fully deployed and active:

```shell
watch juju status --color
```

By default, no partitions are allocated for the new unit `3`,
that should have broker id `103`.
Check that via the log directory assignment:

```bash
juju ssh kafka/leader sudo -i charmed-kafka.log-dirs --describe \
  --bootstrap-server <unit-ip>:19093 \
  --command-config '$CONF/client.properties' \
  2>/dev/null \
  | sed -n '/^{/p' \
  | jq '.brokers[] | select(.broker == 103)'
```

This should produce output similar to the result seen below,
with no partitions allocated by default:

```json
{
  "broker": 103,
  "logDirs": [
    {
      "error": null,
      "logDir": "/var/snap/charmed-kafka/common/var/lib/kafka/data/11/log",
      "partitions": []
    }
  ]
}
```

Now, let's run the `rebalance` action to allocate some existing partitions
from other brokers (`0`, `1` and `2`) to broker `3`:

```bash
juju run cruise-control/0 rebalance mode=add brokerid=103 --wait=2m
```

```{warning}
If this action fails with a message similar to
`Cruise Control balancer service has not yet collected enough data to provide a partition
reallocation proposal`, wait for at least 20 minutes and try again.
Cruise Control takes a long time (sometimes more than an hour) to collect sufficient metrics
from an Apache Kafka cluster during a cold deployment.
```

By default, the `rebalance` action runs as a "dryrun", where the returned result
is what **would** happen were the partition rebalance actually executed.
The action output has detailed information on the proposed allocation.

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

If we are happy with this proposal, we can re-run the action,
but this time instructing the charm to actually execute the proposal:

```bash
juju run cruise-control/0 rebalance mode=add dryrun=false brokerid=103 --wait=10m
```

Partition rebalancing can take significant time.
To monitor the progress, in a separate terminal session, check the `juju debug-log` command output
to see it in progress:

```text
unit-cruise-control-0: 22:18:41 INFO unit.cruise-control/0.juju-log Waiting for task execution to finish for user_task_id='d3e426a3-6c2e-412e-804c-8a677f2678af'...
unit-cruise-control-0: 22:18:51 INFO unit.cruise-control/0.juju-log Waiting for task execution to finish for user_task_id='d3e426a3-6c2e-412e-804c-8a677f2678af'...
unit-cruise-control-0: 22:19:02 INFO unit.cruise-control/0.juju-log Waiting for task execution to finish for user_task_id='d3e426a3-6c2e-412e-804c-8a677f2678af'...
unit-cruise-control-0: 22:19:12 INFO unit.cruise-control/0.juju-log Waiting for task execution to finish for user_task_id='d3e426a3-6c2e-412e-804c-8a677f2678af'...
...
```

Once the action is complete, verify the partitions on the newly added unit
using the same commands as before:

```bash
juju ssh kafka/leader sudo -i charmed-kafka.log-dirs --describe \
  --bootstrap-server <unit-ip>:19093 \
  --command-config '$CONF/client.properties' \
  2>/dev/null \
  | sed -n '/^{/p' \
  | jq '.brokers[] | select(.broker == 103)'
```

This should produce an output similar to the result seen below, with broker `3` now having assigned partitions present, completing the adding of a new broker to the cluster:

```json
{
  "broker": 103,
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

To safely scale-in an Apache Kafka cluster, we must make sure to carefully move any existing data
from units about to be removed, to another unit that will persist.

In practice, this means running a `rebalance` Juju action as seen above,
**BEFORE** scaling down the application. This ensures that data is moved,
prior to the unit becoming unreachable and permanently losing the data on it.

```{note}
As partition data is replicated across a finite number of units based on the value
of the Apache Kafka cluster's `replication.factor` property (default value is `3`)
it is imperative to remove only one broker at a time, to avoid losing all available
replicas for a given partition.
```

To remove the most recent broker unit `3` from the previous example,
re-run the `rebalance` action with `mode=remove`:

```bash
juju run cruise-control/0 rebalance mode=remove dryrun=false brokerid=3 --wait=10m
```

This does not remove the unit, but moves the partitions from the broker on unit number `3`
to other brokers within the cluster.

Once the action has been completed, verify that broker `3` no longer has any assigned partitions:

```bash
juju ssh kafka/leader sudo -i charmed-kafka.log-dirs --describe \
  --bootstrap-server <unit-ip>:19093 \
  --command-config '$CONF/client.properties' \
  2>/dev/null \
  | sed -n '/^{/p' \
  | jq '.brokers[] | select(.broker == 103)'
```

Make sure that the broker has no partitions assigned, for example:

```json
{
  "broker": 103,
  "logDirs": [
    {
      "partitions": [],
      "error": null,
      "logDir": "/var/snap/charmed-kafka/common/var/lib/kafka/data/11/log"
    }
  ]
}
```

Now, it is safe to scale-in the cluster by removing the broker number `3` completely:

```bash
juju remove-unit kafka/3
```

## Full cluster rebalancing

Over time, an Apache Kafka cluster in production may develop an imbalance in partition allocation,
with some brokers having greater/fewer allocated than others.
This can occur as topic load fluctuates, partitions are added or removed due to reconfiguration,
or new topics are created or deleted. Therefore, as part of regular cluster maintenance,
administrators should periodically redistribute partitions across existing broker units
to ensure optimal performance.

Unlike `Adding new brokers` or `Removing old brokers`, this includes a full re-shuffle
of partition allocation across all currently live broker units.

To achieve this, re-run the `rebalance` action with the `mode=full`.
You can do it in the "dryrun" mode (by default) for now:

```bash
juju run cruise-control/0 rebalance mode=full --wait=10m
```

Looking at the bottom of the output, see the value of the `balancedness` score
before and after the proposed 'full' rebalance:

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
