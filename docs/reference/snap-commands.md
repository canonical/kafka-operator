(reference-snap-commands)=
# Snap commands

Charmed Apache Kafka uses the `charmed-kafka` snap to install and operate the underlying Apache Kafka workload. These charms also wrap the upstream Apache Kafka Bash scripts bundled by upstream, as well as additional extra components selected for the charm to operate and manage, for example [LinkedIn's Cruise Control for Apache Kafka](https://github.com/linkedin/cruise-control).

Snap commands and apps are used to ensure that the underlying executables are always ran with the correct environment settings (configuration files, logging files, etc). 

Below is a reference table for the mapping between snap commands and apps with their associated executable :

|                  Snap Command                   |                         Executable                             |
|:-----------------------------------------------:|:--------------------------------------------------------------:|
| `charmed-kafka.daemon`                          | `$SNAP/opt/kafka/bin/kafka-server-start.sh`                  |
| `charmed-kafka.cruise-control`                  | `$SNAP/opt/cruise-control/bin/kafka-cruise-control-start.sh` |
| `charmed-kafka.log-dirs`                        | `$SNAP/opt/kafka/bin/kafka-log-dirs.sh`                      |
| `charmed-kafka.storage`                         | `$SNAP/opt/kafka/bin/storage.sh`                             |
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
| `charmed-kafka.connect-distributed`             | `$SNAP/opt/kafka/bin/connect-distributed.sh`                 |
| `charmed-kafka.connect-plugin-path`             | `$SNAP/opt/kafka/bin/connect-plugin-path.sh`                 |
| `charmed-kafka.keytool`                         | `$SNAP/usr/lib/jvm/java-21-openjdk-amd64/bin/keytool`        |

All of these commands can also be listed with:

```shell
snap info charmed-kafka
```

