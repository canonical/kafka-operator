---
myst:
  html_meta:
    description: "Upgrade Charmed Apache Kafka between versions - in-place minor upgrades with rolling restart and rollback procedures."
---

(how-to-upgrade)=
# How to upgrade between versions

This guide applies for in-place upgrades that involve (at most) minor version upgrade of Apache Kafka workload, e.g. between Apache Kafka 4.0.x to 4.1.x.

```{warning}
In-place upgrades across major workload versions are **NOT SUPPORTED**.
See [full cluster-to-cluster migrations](how-to-cluster-migration) for major version upgrades (for example, from Apache Kafka 3.x to 4.x).
```

Since the charm's code pins a specific workload version, upgrading the charm's revision may include updates to the operator code and/or a minor workload version upgrade.

When upgrading a Charmed Apache Kafka cluster, ensure that no other major operations are performed until the upgrade is complete. This includes, but is not limited to, the following:

1. Adding or removing units
2. Creating or destroying new relations
3. Changes in workload configuration
4. Upgrading other connected applications

The concurrency with other operations is not supported, and it can lead the cluster into inconsistent states.

Note that the process for upgrading a Charmed Apache Kafka KRaft controller
cluster is identical to that of a Charmed Apache Kafka broker cluster. See the
[deployment guide](how-to-deploy-anywhere) for the supported topologies on each
substrate.

```{warning}
Always upgrade the KRaft controller application before upgrading the Kafka broker application to avoid metadata missmatches.
```

## Minor upgrade process

When performing an in-place upgrade process, the full process is composed of the following high-level steps:

1. **Configure** desired refresh behavior with `pause-after-unit-refresh`
2. **Collect** all necessary pre-refresh information, necessary for a rollback (if ever needed)
3. **Prepare** the charm for the in-place upgrade, by running some preparatory tasks 
4. **Upgrade** the charm and/or the workload. Once started, all units in a cluster will refresh the charm code and undergo a workload restart/update. The upgrade will be halted if the unit upgrade has failed, requiring the admin user to roll back.

### Step 1. Configure

For highly available, stateful applications, it is often desirable to upgrade a single unit first, then pause to perform manual validations before continuing. If the upgrade fails, for example, due to a bug or an unforeseen version incompatibility, the impact is limited to that single unit. When the application is replicated across multiple nodes, this approach ensures no measurable disruption to the production service.

Charmed Apache Kafka exposes the `pause-after-unit-refresh` configuration option to help control this pausing behavior. Its default differs by substrate: the VM charm defaults to `none` (no pause), while the K8s charm defaults to `first` (pause once, after the first refreshed unit).

To change refresh pausing behavior, set this configuration option **before** triggering a Juju refresh:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```shell
juju config kafka pause-after-unit-refresh="all"
```

This will now pause the refresh after each unit has upgraded, before waiting for confirmation.

If you only wish to pause once, before letting the refresh proceed unhindered, set:

```shell
juju config kafka pause-after-unit-refresh="first"
```

This will only pause after the first unit has completed it's upgrade.

The VM charm defaults to `none`.

````

````{tab-item} K8s
:sync: k8s

```shell
juju config kafka-k8s pause-after-unit-refresh="all"
```

This pauses after every unit. To proceed without pauses, set:

```shell
juju config kafka-k8s pause-after-unit-refresh="none"
```

The K8s charm defaults to `first`, which pauses once after the first refreshed
unit.

````

`````

(step-2-collect)=
### Step 2: Collect

The second step is to record the revisions of the running application as a safety measure in case a rollback is needed. To check the revisions, run the `juju status` command and find the required Charmed Apache Kafka application. Alternatively, you can retrieve this information with the following command using [yq](https://snapcraft.io/install/yq/ubuntu):

```shell
KAFKA_CHARM_REVISION=$(juju status --format json | yq .applications.<KAFKA_APP_NAME>.charm-rev)
```

### Step 3: Prepare

Next, perform preparatory tasks to define the upgrade plan, ensuring the process can proceed safely.

To do so, run the `pre-refresh-check` action against the leader unit:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```shell
juju run kafka/leader pre-refresh-check
```

````

````{tab-item} K8s
:sync: k8s

```shell
juju run kafka-k8s/leader pre-refresh-check
```

````

`````

Make sure that the output of the action is successful.

```{note}
Although optional, this action should always be run before Charmed Apache Kafka upgrades for production deployments.
```

### Step 4: Upgrade

Use the [`juju refresh`](https://canonical.com/juju/docs/juju-cli/3.6/reference/juju-cli/list-of-juju-cli-commands/refresh/) command to trigger the charm upgrade process.
Note that the upgrade can be performed against:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

* selected channel/track, therefore upgrading to the latest revision published on that track:

  ```shell
  juju refresh kafka --channel 4/stable
  ```
* selected revision:

  ```shell
  juju refresh kafka --revision=<REVISION>
  ```
* a local charm file:

  ```shell
  juju refresh kafka --path ./kafka_ubuntu-24.04-amd64.charm
  ```

````

````{tab-item} K8s
:sync: k8s

* selected channel/track:

  ```shell
  juju refresh kafka-k8s --channel 4/stable
  ```
* selected revision:

  ```shell
  juju refresh kafka-k8s --revision=<REVISION>
  ```
* a local charm file:

  ```shell
  juju refresh kafka-k8s --path ./kafka-k8s_ubuntu-24.04-amd64.charm
  ```

````

`````

When issuing the commands, all units will refresh (i.e. receive new charm content), and the upgrade charm event will be fired. The charm will take care of executing an update (if required) and a restart of the workload one unit at a time to not lose high availability. 

If the `pause-after-unit-refresh` configuration is either `all` or `first`, at some point during the refresh, human intervention will be needed in order to resume the upgrade.

Once all checks, both from the charm and any additional checks determined by the administrator have successfully completed, resume the upgrade by running a Juju action:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```shell
juju run kafka/<unit-id> resume-refresh
```

````

````{tab-item} K8s
:sync: k8s

```shell
juju run kafka-k8s/<unit-id> resume-refresh
```

````

`````

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

While the upgrade is in progress, it is possible to roll back to the original
charm revision.

```{warning}
Rolling back the charm revision does not automatically roll back the workload:
minor workload version downgrades are rejected by the charm, and KRaft metadata
version downgrades are not supported by Apache Kafka. A rollback is therefore
only safe while the workload itself has not yet been upgraded on the paused
units, or when the original and target workload versions are compatible.
```

```{note}
On Kubernetes, also record the `kafka-image` resource in use before the upgrade
with `juju resources <KAFKA_APP_NAME>`, and pass it back with
`juju refresh ... --resource kafka-image=<image>` when rolling back a locally
deployed charm.
```

To rollback, use the `juju refresh` command with the original charm revision:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```shell
juju refresh kafka --revision $KAFKA_CHARM_REVISION
```

````

````{tab-item} K8s
:sync: k8s

```shell
juju refresh kafka-k8s --revision $KAFKA_CHARM_REVISION
```

````

`````

where `KAFKA_CHARM_REVISION` was obtained earlier in [Step 2: Collect](step-2-collect) before the refresh was triggered.
