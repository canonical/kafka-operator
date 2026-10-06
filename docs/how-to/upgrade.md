(how-to-upgrade)=
# How to upgrade between versions

This guide applies for in-place upgrades that involve (at most) minor version upgrade of Apache Kafka workload, e.g. between Apache Kafka 3.4.x to 3.5.x.

```{warning}
In-place upgrades across major workload versions are **NOT SUPPORTED*.
See [full cluster-to-cluster migrations](how-to-cluster-replication-migrate-a-cluster) for major version upgrades (for example, from Apache Kafka 3.x to 4.x).
```

Since the charm's code pins a specific workload version, upgrading the charm's revision may include updates to the operator code and/or a minor workload version upgrade.

While upgrading an Apache Kafka cluster, do not perform any other major operations, including, but not limited to, the following:

1. Adding or removing units
2. Creating or destroying new relations
3. Changes in workload configuration
4. Upgrading other connected applications (e.g. Charmed Apache ZooKeeper)

The concurrency with other operations is not supported, and it can lead the cluster into inconsistent states.

## Minor upgrade process overview

When performing an in-place upgrade process, the full process is composed of the following high-level steps:

1. **Collect** all necessary pre-upgrade information, necessary for a rollback (if ever needed)
2. **Prepare** the charm for the in-place upgrade, by running some preparatory tasks 
3. **Upgrade** the charm and/or the workload. Once started, all units in a cluster will refresh the charm code and undergo a workload restart/update. The upgrade will be aborted if the unit upgrade has failed, requiring the admin user to roll back.
4. **Post-upgrade checks** to make sure all units are in the proper state and the cluster is healthy.

### Step 1: Collect

The first step is to record the revisions of the running application, as a safety measure for a rollback action if needed. To accomplish this, simply run the `juju status` command and look for the revisions of the deployed Charmed Apache Kafka K8s and Charmed Apache ZooKeeper K8s applications. You can also retrieve this with the following command (that requires [`yq`](https://snapcraft.io/install/yq/ubuntu) to be installed):

```shell
KAFKA_CHARM_REVISION=$(juju status --format json | yq .applications.<KAFKA_APP_NAME>.charm-rev)
ZOOKEEPER_CHARM_REVISION=$(juju status --format json | yq .applications.<ZOOKEEPER_APP_NAME>.charm-rev)
```

Please fill `<KAFKA_APP_NAME>` and `<ZOOKEEPER_APP_NAME>}` placeholder appropriately, e.g. `kafka-k8s` and `zookeeper-k8s`.

### Step 2: Prepare

Before upgrading, the charm needs to perform some preparatory tasks to define the upgrade plan.  
To do so, run the `pre-upgrade-check` action against the leader unit:

```shell
juju run kafka/leader pre-upgrade-check --format yaml
```

Make sure that the output of the action is successful.

```{note}
This action must be run before Charmed Apache Kafka K8s upgrades.
```

The action will also configure the charm to minimise high-availability reduction and ensure a safe upgrade process. After successful execution, the charm is ready to be upgraded.

### Step 3: Upgrade

Use the [`juju refresh`](https://juju.is/docs/juju/juju-refresh) command to trigger the charm upgrade process.
Note that the upgrade can be performed against:

* selected channel/track, therefore upgrading to the latest revision published on that track:

  ```shell
  juju refresh kafka-k8s --channel 3/edge
  ```

* selected revision:

  ```shell
  juju refresh kafka-k8s --revision=<REVISION>
  ```

* a local charm file:

  ```shell
  juju refresh kafka-k8s --path ./kafka_ubuntu-22.04-amd64.charm
  ```

When issuing the commands, only the unit with the largest ordinal number will refresh (i.e. receive new charm content).
A new pod will be rescheduled with the new image and/or the new charm revision.
As the Pod starts, the upgrade charm event will be fired on the pod, running 
any custom logic required during the upgrade. 

Once the unit is returned active and healthy, the charm will block the upgrade process, to provide 
a way for the user to manually check that the new version works properly 
and make sure everything is fine before rolling out the upgrade also on the remaining units. 

If the manual checks are successful, the upgrade process can be resumed with 

```
juju run kafka-k8s/leader resume-upgrade --format yaml  --wait=1m 
```

```{note}
Even though the process will not stop anymore on each upgrade, 
the charm will take care of coordinating the pod updates by restarting one unit at a time to not lose high availability. 
This generally keeps the Apache Kafka service up and running during an upgrade, although downtime should be tolerated during upgrades.
```

The upgrade process can be monitored using `juju status` command, where the message of the units will provide information about which units have been upgraded already, which unit is currently upgrading and which units are waiting for the upgrade to be triggered, as shown below: 

```shell
...

App        Version  Status  Scale  Charm      Channel   Rev  Exposed  Message
kafka               active      3  kafka      3/stable  147  no

Unit          Workload  Agent  Address       Ports  Message
...
kafka/0       active    idle   10.193.41.131        Other units upgrading first...
kafka/1*      active    idle   10.193.41.109        Upgrading...
kafka/2       active    idle   10.193.41.221        Upgrade completed
...

```

#### Failing upgrade

Before upgrading the unit, the charm will check whether the upgrade can be performed, e.g. this may mean:

1. Checking that the upgrade from the previous charm revision and Apache Kafka version is allowed.
2. Checking that other external applications that Apache Kafka depends on (e.g. Apache ZooKeeper) are running the correct version.

Note that these checks are only possible after a refresh of the charm code, and therefore cannot be done upfront (e.g. during the `pre-upgrade-checks` action).
If some of these checks fail, the upgrade will be aborted. When this happens, the workload may still be operating (as only the operator may have failed) but we recommend rolling back the upgrade as soon as possible. 

To roll back the upgrade, re-run steps #2 and #3, using the revision taken in step 1:

```shell
juju run kafka-k8s/leader pre-upgrade-check

juju refresh kafka-k8s --revision=${KAFKA_CHARM_REVISION}
```

We strongly recommend to also retrieve the full set of logs with `juju debug-log`, to extract insights on why the upgrade failed. 

## Combined upgrades

If Charmed Apache Kafka K8s and Charmed Apache ZooKeeper K8s both need to be upgraded, we recommend starting the upgrade from the Charmed Apache ZooKeeper. As outlined above, the two upgrades should **NEVER** be done concurrently.
