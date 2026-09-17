---
myst:
  html_meta:
    description: "Charmed Apache Kafka snap commands reference - complete mapping of snap commands to executable scripts."
---

(reference-snap-commands)=
# Snap commands

Charmed Apache Kafka uses the `charmed-kafka` snap to install and operate the underlying Apache Kafka workload. These charms also wrap the upstream Apache Kafka Bash scripts bundled by upstream, as well as additional extra components selected for the charm to operate and manage, for example [LinkedIn's Cruise Control for Apache Kafka](https://github.com/linkedin/cruise-control).

Snap commands and apps are used to ensure that the underlying executables are always ran with the correct environment settings (configuration files, logging files, etc). 

Below is a reference table for the mapping between snap commands and apps with their associated
executable. Unless otherwise noted, commands are invoked through `bin-wrapper.bash`,
which sets default logging options before running the target script. Exceptions are noted
in the table: the three commands that start long-running services
(`daemon`, `cruise-control`, `connect-distributed`) use a dedicated wrapper, and `keytool`
has no wrapper at all. See {ref}`reference-snap-commands-wrapper-scripts` for details.

|                  Snap Command                   |                         Executable                             |
|:-----------------------------------------------:|:--------------------------------------------------------------:|
| `charmed-kafka.daemon`                          | `$SNAP/opt/kafka/bin/kafka-server-start.sh` (via `start-wrapper.bash`) |
| `charmed-kafka.cruise-control`                  | `$SNAP/opt/cruise-control/bin/kafka-cruise-control-start.sh` (via `start-wrapper.bash`) |
| `charmed-kafka.log-dirs`                        | `$SNAP/opt/kafka/bin/kafka-log-dirs.sh`                      |
| `charmed-kafka.storage`                         | `$SNAP/opt/kafka/bin/kafka-storage.sh`                       |
| `charmed-kafka.consumer-perf-test`              | `$SNAP/opt/kafka/bin/kafka-consumer-perf-test.sh`            |
| `charmed-kafka.producer-perf-test`              | `$SNAP/opt/kafka/bin/kafka-producer-perf-test.sh`            |
| `charmed-kafka.configs`                         | `$SNAP/opt/kafka/bin/kafka-configs.sh`                       |
| `charmed-kafka.topics`                          | `$SNAP/opt/kafka/bin/kafka-topics.sh`                        |
| `charmed-kafka.console-consumer`                | `$SNAP/opt/kafka/bin/kafka-console-consumer.sh`              |
| `charmed-kafka.console-producer`                | `$SNAP/opt/kafka/bin/kafka-console-producer.sh`              |
| `charmed-kafka.consumer-groups`                 | `$SNAP/opt/kafka/bin/kafka-consumer-groups.sh`               |
| `charmed-kafka.get-offsets`                     | `$SNAP/opt/kafka/bin/kafka-get-offsets.sh`                   |
| `charmed-kafka.reassign-partitions`             | `$SNAP/opt/kafka/bin/kafka-reassign-partitions.sh`           |
| `charmed-kafka.replica-verification`            | `$SNAP/opt/kafka/bin/kafka-replica-verification.sh`          |
| `charmed-kafka.run-class`                       | `$SNAP/opt/kafka/bin/kafka-run-class.sh`                     |
| `charmed-kafka.kafka-streams-application-reset` | `$SNAP/opt/kafka/bin/kafka-streams-application-reset.sh`     |
| `charmed-kafka.transactions`                    | `$SNAP/opt/kafka/bin/kafka-transactions.sh`                  |
| `charmed-kafka.leader-election`                 | `$SNAP/opt/kafka/bin/kafka-leader-election.sh`              |
| `charmed-kafka.dump-log`                        | `$SNAP/opt/kafka/bin/kafka-dump-log.sh`                      |
| `charmed-kafka.acls`                            | `$SNAP/opt/kafka/bin/kafka-acls.sh`                          |
| `charmed-kafka.cluster`                         | `$SNAP/opt/kafka/bin/kafka-cluster.sh`                       |
| `charmed-kafka.verifiable-consumer`             | `$SNAP/opt/kafka/bin/kafka-verifiable-consumer.sh`           |
| `charmed-kafka.verifiable-producer`             | `$SNAP/opt/kafka/bin/kafka-verifiable-producer.sh`           |
| `charmed-kafka.trogdor`                         | `$SNAP/opt/kafka/bin/trogdor.sh`                             |
| `charmed-kafka.metadata-quorum`                 | `$SNAP/opt/kafka/bin/kafka-metadata-quorum.sh`               |
| `charmed-kafka.connect-distributed`             | `$SNAP/opt/kafka/bin/connect-distributed.sh` (via `connect-wrapper.bash`) |
| `charmed-kafka.connect-plugin-path`             | `$SNAP/opt/kafka/bin/connect-plugin-path.sh`                 |
| `charmed-kafka.keytool`                         | `$SNAP/usr/lib/jvm/java-21-openjdk-amd64/bin/keytool` (no wrapper) |

All of these commands can also be listed with:

```shell
snap info charmed-kafka
```

(reference-snap-commands-wrapper-scripts)=
## Wrapper scripts

There are two kinds of wrapper scripts:

* `bin-wrapper.bash` — used by most commands. It only sets default logging options before running the target script.
* `start-wrapper.bash`/`connect-wrapper.bash` — used by `daemon`, `cruise-control` and `connect-distributed` to start their respective long-running services. In addition to setting logging options, these drop root privileges to the confined `_daemon_` user (via `setpriv`) before starting the service.

`keytool` is the only command with no wrapper — it invokes the JVM `keytool` binary directly.

Both wrapper types set the `KAFKA_LOG4J_OPTS` and `KAFKA_JMX_OPTS` environment variables
**only if they are not already set**, and point them at snap-specific paths, for example
`${SNAP_DATA}/etc/kafka/log4j2.yaml`. This env-var-based override pattern is inherited from upstream
Apache Kafka's own `bin/kafka-run-class.sh`;
see the [Configuration](https://kafka.apache.org/41/configuration/) and
[Monitoring](https://kafka.apache.org/41/operations/monitoring/#security-considerations-for-remote-monitoring-using-jmx)
documentation for details on `KAFKA_LOG4J_OPTS`, `KAFKA_JMX_OPTS`, `JMX_PORT` and related variables.

The `charmed.kafka.log.level` property injected into `KAFKA_LOG4J_OPTS` is specific to the
`charmed-kafka` snap's own `log4j2.yaml` template, and is not an upstream Apache Kafka property.
