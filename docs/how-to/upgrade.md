(how-to-upgrade)=
# How to upgrade between versions

This guide applies for in-place upgrades that involve (at most) minor version upgrade of Apache Kafka workload, e.g. between Apache Kafka 4.0.x to 4.1.x.

```{warning}
In-place upgrades across major workload versions are **NOT SUPPORTED*.
See [full cluster-to-cluster migrations](how-to-cluster-migration) for major version upgrades (for example, from Apache Kafka 3.x to 4.x).
```

Since the charm's code pins a specific workload version, upgrading the charm's revision may include updates to the operator code and/or a minor workload version upgrade.

When upgrading a Charmed Apache Kafka cluster, ensure that no other major operations are performed until the upgrade is complete. This includes, but is not limited to, the following:

1. Adding or removing units
2. Creating or destroying new relations
3. Changes in workload configuration
4. Upgrading other connected applications

The concurrency with other operations is not supported, and it can lead the cluster into inconsistent states.

## Minor upgrade process

When performing an in-place upgrade process, the full process is composed of the following high-level steps:

1. **Configure** desired refresh behavior with `pause-after-unit-refresh`
2. **Collect** all necessary pre-upgrade information, necessary for a rollback (if ever needed)
3. **Prepare** the charm for the in-place upgrade, by running some preparatory tasks 
4. **Upgrade** the charm and/or the workload. Once started, all units in a cluster will refresh the charm code and undergo a workload restart/update. The upgrade will be halted if the unit upgrade has failed, requiring the admin user to roll back.

### Step 1. Configure

For highly available, stateful applications, it is often desirable to upgrade a single unit first, then pause to perform manual validations before continuing. If the upgrade fails, for example, due to a bug or an unforeseen version incompatibility, the impact is limited to that single unit. When the application is replicated across multiple nodes, this approach ensures no measurable disruption to the production service.

Charmed Apache Kafka exposes the `pause-after-unit-refresh` configuration option to help control this pausing behavior. By default, this option is set to `none`, meaning that a refresh will complete without a pause for manual checks.

To change refresh pausing behavior, set this configuration option **before** triggering a Juju refresh:

```shell
juju config kafka pause-after-unit-refresh="all"
```

This will now pause the refresh after each unit has upgraded, before waiting for confirmation.

If you only wish to pause once, before letting the refresh proceed unhindered, set:

```shell
juju config kafka pause-after-unit-refresh="first"
```

This will only pause after the first unit has completed it's upgrade.

(step-2-collect)=
### Step 2: Collect

The second step is to record the revisions of the running application as a safety measure in case a rollback is needed. To check the revisions, run the `juju status` command and find the required Charmed Apache Kafka application. Alternatively, you can retrieve this information with the following command using [yq](https://snapcraft.io/install/yq/ubuntu):

```shell
KAFKA_CHARM_REVISION=$(juju status --format json | yq .applications.<KAFKA_APP_NAME>.charm-rev)
```

### Step 3: Prepare

Next, perform preparatory tasks to define the upgrade plan, ensuring the process can proceed safely.

To do so, run the `pre-upgrade-check` action against the leader unit:

```shell
juju run kafka/leader pre-upgrade-check 
```

Make sure that the output of the action is successful.

```{note}
Although optional, this action should always be run before Charmed Apache Kafka upgrades for production deployments.
```

### Step 4: Upgrade

Use the [`juju refresh`](https://juju.is/docs/juju/juju-refresh) command to trigger the charm upgrade process.
Note that the upgrade can be performed against:

* selected channel/track, therefore upgrading to the latest revision published on that track:

  ```shell
  juju refresh kafka --channel 4/edge
  ```
* selected revision:

  ```shell
  juju refresh kafka --revision=<REVISION>
  ```
* a local charm file:

  ```shell
  juju refresh kafka --path ./kafka_ubuntu-24.04-amd64.charm
  ```

When issuing the commands, all units will refresh (i.e. receive new charm content), and the upgrade charm event will be fired. The charm will take care of executing an update (if required) and a restart of the workload one unit at a time to not lose high availability. 

If the `pause-after-unit-refresh` configuration is either `all` or `first`, at some point during the refresh, human intervention will be needed in order to resume the upgrade.

Once all checks, both from the charm and any additional checks determined by the administrator have successfully completed, resume the upgrade by running a Juju action:

```shell
juju run kafka/<unit-id> resume-refresh
```

```{note}
Run this action on the next unit scheduled for refresh, as indicated in the application status.
```

The upgrade process can be monitored using `juju status` command, where the message of the units will provide information about which units have been upgraded already, which unit is currently upgrading and which units are waiting for the upgrade to be triggered, as shown below: 

```shell
App        Version  Status  Scale  Charm      Channel   Rev  Exposed  Message
kafka               active      4  kafka      4/stable  147  no

Unit          Workload  Agent  Machine  Public address  Ports  Message
kafka/0       active    idle   3        10.193.41.131          Other units upgrading first...
kafka/1*      active    idle   4        10.193.41.109          Upgrading...
kafka/2       active    idle   5        10.193.41.221          Upgrade completed
```

#### Rollbacks

At any point in the upgrade, it is possible to safely rollback to the original charm revision.

To rollback, use the `juju refresh` command with the original charm revision:

```shell
juju refresh kafka --revision KAFKA_CHARM_REVISION
```

where `KAFKA_CHARM_REVISION` was obtained earlier in [Step 2: Collect](step-2-collect) before the refresh was triggered.
