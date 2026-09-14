---
myst:
  html_meta:
    description: "Charmed Apache Kafka command-line utilities on machines and Kubernetes, including snap commands and container scripts."
---

(reference-cli-utilities)=
(reference-snap-commands)=
# Command-line utilities

Charmed Apache Kafka includes the Apache Kafka command-line utilities on both
substrates. The packaging and invocation differ:

* On machines, the `charmed-kafka` snap exposes commands named
  `charmed-kafka.<command>`.
* On Kubernetes, the utilities are executable scripts in the workload
  container. Apache Kafka scripts are under `/opt/kafka/bin`, Cruise Control is
  under `/opt/cruise-control/bin`, and `keytool` is available on `PATH`.

## Run a utility

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

Run a snap command on a Kafka unit:

```shell
juju ssh kafka/leader sudo -i \
  'charmed-kafka.<command> <arguments>'
```

For example:

```shell
juju ssh kafka/leader sudo -i \
  'charmed-kafka.topics \
    --bootstrap-server <bootstrap-server> \
    --command-config /var/snap/charmed-kafka/current/etc/kafka/client.properties \
    --list'
```

List all snap applications with:

```shell
snap info charmed-kafka
```

````

````{tab-item} K8s
:sync: k8s

Run an Apache Kafka or Cruise Control executable in the `kafka` workload
container:

```shell
juju ssh --container kafka kafka-k8s/leader \
  '<absolute-path> <arguments>'
```

For example:

```shell
juju ssh --container kafka kafka-k8s/leader \
  '/opt/kafka/bin/kafka-topics.sh \
    --bootstrap-server <bootstrap-server> \
    --command-config /etc/kafka/client.properties \
    --list'
```

For Kafka Connect utilities, use the `kafka-connect` workload container:

```shell
juju ssh --container kafka-connect kafka-connect-k8s/leader \
  '/opt/kafka/bin/connect-plugin-path.sh --help'
```

Use absolute paths on Kubernetes. Variables such as `$BIN` and `$CONF`, and the
environment assigned to a Pebble service, are not guaranteed to be present in
an interactive command.

````

`````

```{tip}
Commands enclosed in single quotes are expanded inside the unit or container.
Use double quotes if a variable defined in your local shell must be expanded
before the command is sent through `juju ssh`.
```

## Command mapping

| Purpose | Machine snap command | Kubernetes executable | Kubernetes container |
|---|---|---|---|
| Kafka service entry point | `charmed-kafka.daemon` | `/opt/kafka/bin/kafka-server-start.sh` | `kafka` |
| Cruise Control service entry point | `charmed-kafka.cruise-control` | `/opt/cruise-control/bin/kafka-cruise-control-start.sh` | `kafka` |
| Describe log directories | `charmed-kafka.log-dirs` | `/opt/kafka/bin/kafka-log-dirs.sh` | `kafka` |
| Format or inspect storage | `charmed-kafka.storage` | `/opt/kafka/bin/kafka-storage.sh` | `kafka` |
| Consumer performance test | `charmed-kafka.consumer-perf-test` | `/opt/kafka/bin/kafka-consumer-perf-test.sh` | `kafka` |
| Producer performance test | `charmed-kafka.producer-perf-test` | `/opt/kafka/bin/kafka-producer-perf-test.sh` | `kafka` |
| Manage configuration | `charmed-kafka.configs` | `/opt/kafka/bin/kafka-configs.sh` | `kafka` |
| Manage topics | `charmed-kafka.topics` | `/opt/kafka/bin/kafka-topics.sh` | `kafka` |
| Console consumer | `charmed-kafka.console-consumer` | `/opt/kafka/bin/kafka-console-consumer.sh` | `kafka` |
| Console producer | `charmed-kafka.console-producer` | `/opt/kafka/bin/kafka-console-producer.sh` | `kafka` |
| Manage consumer groups | `charmed-kafka.consumer-groups` | `/opt/kafka/bin/kafka-consumer-groups.sh` | `kafka` |
| Get topic offsets | `charmed-kafka.get-offsets` | `/opt/kafka/bin/kafka-get-offsets.sh` | `kafka` |
| Reassign partitions | `charmed-kafka.reassign-partitions` | `/opt/kafka/bin/kafka-reassign-partitions.sh` | `kafka` |
| Verify replicas | `charmed-kafka.replica-verification` | `/opt/kafka/bin/kafka-replica-verification.sh` | `kafka` |
| Run a Kafka class | `charmed-kafka.run-class` | `/opt/kafka/bin/kafka-run-class.sh` | `kafka` |
| Reset a Streams application | `charmed-kafka.kafka-streams-application-reset` | `/opt/kafka/bin/kafka-streams-application-reset.sh` | `kafka` |
| Manage transactions | `charmed-kafka.transactions` | `/opt/kafka/bin/kafka-transactions.sh` | `kafka` |
| Trigger leader election | `charmed-kafka.leader-election` | `/opt/kafka/bin/kafka-leader-election.sh` | `kafka` |
| Inspect log segments | `charmed-kafka.dump-log` | `/opt/kafka/bin/kafka-dump-log.sh` | `kafka` |
| Manage ACLs | `charmed-kafka.acls` | `/opt/kafka/bin/kafka-acls.sh` | `kafka` |
| Inspect the cluster ID | `charmed-kafka.cluster` | `/opt/kafka/bin/kafka-cluster.sh` | `kafka` |
| Run a verifiable consumer | `charmed-kafka.verifiable-consumer` | `/opt/kafka/bin/kafka-verifiable-consumer.sh` | `kafka` |
| Run a verifiable producer | `charmed-kafka.verifiable-producer` | `/opt/kafka/bin/kafka-verifiable-producer.sh` | `kafka` |
| Run {spellexception}`Trogdor` tests | `charmed-kafka.trogdor` | `/opt/kafka/bin/trogdor.sh` | `kafka` |
| Inspect the KRaft quorum | `charmed-kafka.metadata-quorum` | `/opt/kafka/bin/kafka-metadata-quorum.sh` | `kafka` |
| Kafka Connect service entry point | `charmed-kafka.connect-distributed` | `/opt/kafka/bin/connect-distributed.sh` | `kafka-connect` |
| Inspect the Connect plugin path | `charmed-kafka.connect-plugin-path` | `/opt/kafka/bin/connect-plugin-path.sh` | `kafka-connect` |
| Manage Java keys and certificates | `charmed-kafka.keytool` | `keytool` | `kafka` or `kafka-connect` |

```{warning}
Do not manually start `kafka-server-start.sh`,
`kafka-cruise-control-start.sh`, or `connect-distributed.sh` on a
charm-managed deployment. They are service entry points managed by the charm
through snap services on machines or Pebble on Kubernetes.
```

## Client configuration

Most administrative commands require a bootstrap server and a client
configuration file containing the cluster administrator credentials.

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

* Kafka client configuration:
  `/var/snap/charmed-kafka/current/etc/kafka/client.properties`
* KRaft client configuration:
  `/var/snap/charmed-kafka/current/etc/kafka/kraft-client.properties`

The machine charm also writes `$BIN`, `$CONF`, `$LOGS`, and `$DATA` to
`/etc/environment`.

````

````{tab-item} K8s
:sync: k8s

* Kafka client configuration: `/etc/kafka/client.properties`
* KRaft client configuration: `/etc/kafka/kraft-client.properties`
* Kafka Connect worker configuration:
  `/etc/connect/connect-distributed.properties`

Use absolute paths when invoking commands in a workload container.

````

`````

(reference-cli-utilities-wrapper-scripts)=
(reference-snap-commands-wrapper-scripts)=
## Machine snap wrappers

The machine snap applications add environment settings required by the packaged
workload:

* `bin-wrapper.bash` is used by most Kafka utilities. It sets the Kafka log
  directory and default tool logging configuration, and disables JMX for the
  invocation.
* The Kafka and Cruise Control start wrappers configure their service
  environments and drop privileges to the confined `_daemon_` user.
* `connect-wrapper.bash` sets the Connect logging configuration, disables JMX,
  and starts Connect with the snap-managed worker configuration.
* `charmed-kafka.keytool` invokes the bundled JDK utility directly.

Kubernetes commands invoke the scripts directly and do not use these snap
wrappers. When a command needs custom Java, JMX, or logging settings, provide
the relevant environment variables explicitly.

The `charmed.kafka.log.level` property used by the snap's `log4j2.yaml` is
specific to the `charmed-kafka` package and is not an upstream Apache Kafka
property. For upstream options, see the Apache Kafka
[configuration](https://kafka.apache.org/41/configuration/) and
[JMX monitoring](https://kafka.apache.org/41/operations/monitoring/#security-considerations-for-remote-monitoring-using-jmx)
documentation.
