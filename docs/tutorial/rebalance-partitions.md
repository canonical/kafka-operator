---
myst:
  html_meta:
    description: Rebalance Charmed Apache Kafka partitions using Cruise Control - optimize resource distribution when scaling brokers.
---

<!-- test:spread
priority: -300
kill-timeout: 90m
-->

(tutorial-rebalance-partitions)=

# 7. Rebalance and reassign partitions

This is a part of the [Charmed Apache Kafka Tutorial](index.md).

By default, when adding more brokers to a Charmed Apache Kafka cluster, the current allocated
partitions on the original brokers are not automatically redistributed across the new brokers. This
can lead to inefficient resource usage and over-provisioning. On the other hand, when removing
brokers to reduce capacity, partitions assigned to the removed brokers are also not redistributed,
which can result in under-replicated data at best and permanent data loss at worst.

To address this, we can make use of
[LinkedIn's Cruise Control](https://github.com/linkedin/cruise-control), which is bundled as part of
the Charmed Apache Kafka [snap](https://github.com/canonical/charmed-kafka-snap) and
[rock](https://github.com/canonical/charmed-kafka-rock).

<!-- At a high level, Cruise Control is made up of the following five components:

- **Workload Monitor** - responsible for the metrics collection from Charmed Apache Kafka
- **Analyser** - generates allocation proposals based on configured [Goals](https://github.com/linkedin/cruise-control?tab=readme-ov-file#goals)
- **Anomaly Detector** - detects failures in brokers, disks, metrics or goals and (optionally) self-heals
- **Web server** - a REST API for user operations
- **Executor** - issues re-allocation commands to Apache Kafka -->

The Charmed Apache Kafka charm has a configuration option `roles`, which takes a list of possible
values. Different roles can be configured to run on the same machine, or as separate Juju
applications.

The `balancer` role is required to run Cruise Control. It can be added to either of the Juju
applications: `kafka` with the `broker` role, or `kraft` with the `controller` role.

We recommend combining `controller` and `balancer` roles together on the `kraft` application, due to
higher performance demands of the `broker` role.

## Setup

We already deployed the `kraft` application with `roles=controller,balancer` in the
[Deploy](tutorial-deploy) part of this tutorial, so Cruise Control has been collecting metrics from
the brokers since then. Check the current roles of the `kraft` application:

```shell
juju config kraft roles
```

<!-- test:assert
juju config kraft roles | grep -qw balancer
-->

The output should list both roles:

```text
controller,balancer
```

## Adding new brokers

Let's scale-out the Charmed Apache Kafka application to four units (add one more):

`````{tab-set}
---
sync-group: substrate
---
````{tab-item} VM
:sync: vm

```shell
juju add-unit kafka
```

````

````{tab-item} K8s
:sync: k8s

On Kubernetes, set the desired total number of units instead of adding one:

```bash
juju scale-application kafka 4
```

````

`````

<!-- test:await-idle --timeout 1200 --allow-blocked opensearch -->

<!-- test:assert
test "$(juju status --format json | jq '.applications.kafka.units | length')" -eq 4
-->

Wait for the additional unit to be fully deployed and active:

<!-- test:skip -->

```shell
watch juju status --color
```

<!-- test:set-variables
command: juju show-unit kafka/0 --format json | jq -r '."kafka/0"."public-address"' | awk '{print "unit-ip: " $1}'
KAFKA_UNIT_IP: unit-ip
-->

% The add and remove steps below rely on the charm moving partitions by itself, because
% `rebalance mode=add` and `mode=remove` reject broker IDs such as 103 on 4/stable rev 273.
% Restore the targeted `rebalance` steps (revert the commit that added this note) once
% canonical/kafka-operator#620 is released to 4/stable and canonical/kafka-operator#626 is fixed.

The new unit `3` has the broker ID `103`, which is the unit number offset by `100`. Once Cruise
Control has collected enough metrics from the new broker, the charm moves some of the existing
partitions from the other brokers to it. This can take several minutes.

<!-- test:retry --timeout 2400 --interval 60 --description "Partitions on broker 103" -- broker_has_partitions 103 -->

Check the partitions assigned to broker `103` via the log directory assignment:

`````{tab-set}
---
sync-group: substrate
---
````{tab-item} VM
:sync: vm

```shell
juju ssh kafka/leader sudo -i charmed-kafka.log-dirs --describe \
  --bootstrap-server <unit-ip>:19093 \
  --command-config '$CONF/client.properties' \
  2>/dev/null \
  | sed -n '/^{/p' \
  | jq '.brokers[] | select(.broker == 103)'
```

````

````{tab-item} K8s
:sync: k8s

```bash
juju ssh --container kafka kafka/leader \
  "/opt/kafka/bin/kafka-log-dirs.sh --describe \
  --bootstrap-server <unit-ip>:19093 \
  --command-config /etc/kafka/client.properties" \
  2>/dev/null \
  | sed -n '/^{/p' \
  | jq '.brokers[] | select(.broker == 103)'
```

````

`````

This should produce an output similar to the result seen below, with broker `3` now having assigned
partitions present, completing the adding of a new broker to the cluster:

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

If the `partitions` list is still empty, wait a few minutes and run the command again.

See [File system paths](reference-file-system-paths) for the full mapping of VM snap paths to
container paths.

## Removing old brokers

To safely scale-in an Apache Kafka cluster, we must make sure to carefully move any existing data
from units about to be removed, to another unit that will persist.

With Cruise Control running, the charm does this for you. When a broker unit is removed, the charm
first moves the partitions from this broker to the remaining ones, and only then the unit is
removed.

```{note}
As partition data is replicated across a finite number of units based on the value
of the Apache Kafka cluster's `replication.factor` property (default value is `3`)
it is imperative to remove only one broker at a time, to avoid losing all available
replicas for a given partition.
```

Remove the broker unit `3` that we added in the previous section:

`````{tab-set}
---
sync-group: substrate
---
````{tab-item} VM
:sync: vm

```shell
juju remove-unit kafka/3 --no-prompt
```

````

````{tab-item} K8s
:sync: k8s

On Kubernetes, scale the application back down. Kubernetes removes the
highest-numbered unit, which is the broker that we added in the previous section:

```bash
juju scale-application kafka 3
```

````

`````

<!-- test:run
timeout 2400 bash -c 'until [ "$(juju status --format json | jq ".applications.kafka.units | length")" -eq 3 ]; do sleep 30; done'
-->

<!-- test:await-idle --timeout 1200 --allow-blocked opensearch -->

Moving the partitions can take several minutes. The unit stays in the `juju status` output until
this is complete.

## Full cluster rebalancing

Over time, an Apache Kafka cluster in production may develop an imbalance in partition allocation,
with some brokers having greater/fewer allocated than others. This can occur as topic load
fluctuates, partitions are added or removed due to reconfiguration, or new topics are created or
deleted. Therefore, as part of regular cluster maintenance, administrators should periodically
redistribute partitions across existing broker units to ensure optimal performance.

Unlike `Adding new brokers` or `Removing old brokers`, this includes a full re-shuffle of partition
allocation across all currently live broker units.

To achieve this, run the `rebalance` action with the `mode=full`. You can do it in the "dryrun" mode
(by default) for now:

<!-- test:retry --timeout 1200 --interval 120 --description "Cruise Control full rebalance" -- run_action kraft/leader rebalance mode=full --wait=3m -->

<!-- test:skip -->

```shell
juju run kraft/leader rebalance mode=full --wait=10m
```

```{warning}
If this action fails with a message similar to
`Cruise Control balancer service has not yet collected enough data to provide a partition
reallocation proposal`, wait for at least 20 minutes and try again.
Cruise Control needs some time to collect sufficient metrics from an Apache Kafka cluster after
the `balancer` role is enabled.
```

Looking at the bottom of the output, see the value of the `balancedness` score before and after the
proposed 'full' rebalance:

```text
summary:
  ...
  ondemandbalancednessscoreafter: "90.06926434109423"
  ondemandbalancednessscorebefore: "85.15942156660185"
  ...
```

To implement the proposed changes, run the same command but with `dryrun=false`:

<!-- test:retry --timeout 1200 --interval 120 --description "Full rebalance" -- run_action kraft/leader rebalance mode=full dryrun=false --wait=10m -->

<!-- test:skip -->

```shell
juju run kraft/leader rebalance mode=full dryrun=false --wait=10m
```

Partition rebalancing can take significant time. To monitor the progress, in a separate terminal
session, check the `juju debug-log` command output to see it in progress:

```text
unit-kraft-0: 22:18:41 INFO unit.kraft/0.juju-log Waiting for task execution to finish for user_task_id='d3e426a3-6c2e-412e-804c-8a677f2678af'...
unit-kraft-0: 22:18:51 INFO unit.kraft/0.juju-log Waiting for task execution to finish for user_task_id='d3e426a3-6c2e-412e-804c-8a677f2678af'...
unit-kraft-0: 22:19:02 INFO unit.kraft/0.juju-log Waiting for task execution to finish for user_task_id='d3e426a3-6c2e-412e-804c-8a677f2678af'...
unit-kraft-0: 22:19:12 INFO unit.kraft/0.juju-log Waiting for task execution to finish for user_task_id='d3e426a3-6c2e-412e-804c-8a677f2678af'...
...
```
