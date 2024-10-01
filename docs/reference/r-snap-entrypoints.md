# Charmed Kafka Snap Entrypoints

Snap entrypoints wrap the Kafka Distribution Bash scripts and make sure
that they run with the correct environment settings (configuration files, logging files, etc). 

Below is a reference table for the mapping between entrypoints and wrapped bash script:

| Snap Entrypoint                                 | Kafka Distribution Bash Script                           |
|-------------------------------------------------|----------------------------------------------------------|
| `charmed-kafka.daemon`                          | `$SNAP/opt/kafka/bin/kafka-server-start.sh`              |
| `charmed-kafka.log-dirs`                        | `$SNAP/opt/kafka/bin/kafka-log-dirs.sh`                  |
| `charmed-kafka.storage`                         | `$SNAP/opt/kafka/bin/storage.sh`                         |
| `charmed-kafka.consumer-perf-test`              | `$SNAP/opt/kafka/bin/kafka-consumer-perf-test.sh`        |
| `charmed-kafka.producer-perf-test`              | `$SNAP/opt/kafka/bin/kafka-producer-perf-test.sh`        |
| `charmed-kafka.configs`                         | `$SNAP/opt/kafka/bin/kafka-configs.sh`                   |
| `charmed-kafka.topics`                          | `$SNAP/opt/kafka/bin/kafka-topics.sh`                    |
| `charmed-kafka.console-consumer`                | `$SNAP/opt/kafka/bin/kafka-console-consumer.sh`          |
| `charmed-kafka.console-producer`                | `$SNAP/opt/kafka/bin/kafka-console-producer.sh`          |
| `charmed-kafka.consumer-groups`                 | `$SNAP/opt/kafka/bin/kafka-consumer-groups.sh`           |
| `charmed-kafka.get-offsets`                     | `$SNAP/opt/kafka/bin/kafka-get-offsets.sh`               |
| `charmed-kafka.reassign-partitions`             | `$SNAP/opt/kafka/bin/kafka-reassign-partitions.sh`       |
| `charmed-kafka.replica-verification`            | `$SNAP/opt/kafka/bin/kafka-replica-verification.sh`      |
| `charmed-kafka.zookeeper-shell`                 | `$SNAP/opt/kafka/bin/zookeeper-shell.sh`                 |
| `charmed-kafka.run-class`                       | `$SNAP/opt/kafka/bin/kafka-run-class.sh`                 |
| `charmed-kafka.kafka-streams-application-reset` | `$SNAP/opt/kafka/bin/kafka-streams-application-reset.sh` |
| `charmed-kafka.transactions`                    | `$SNAP/opt/kafka/bin/kafka-transactions.sh`              |
| `charmed-kafka.leader-election`                 | `$SNAP/opt/kafka/bin/kafka-leader-election.sh`           |
| `charmed-kafka.dump-log`                        | `$SNAP/opt/kafka/bin/kafka-dump-log.sh`                  |
| `charmed-kafka.acls`                            | `$SNAP/opt/kafka/bin/kafka-acls.sh`                      |
| `charmed-kafka.cluster`                         | `$SNAP/opt/kafka/bin/kafka-cluster.sh`                   |
| `charmed-kafka.verifiable-consumer`             | `$SNAP/opt/kafka/bin/kafka-verifiable-consumer.sh`       |
| `charmed-kafka.verifiable-producer`             | `$SNAP/opt/kafka/bin/kafka-verifiable-producer.sh`       |
| `charmed-kafka.trogdor`                         | `$SNAP/opt/kafka/bin/trogdor.sh`                         |
| `charmed-kafka.keytool`                         | `$SNAP/usr/lib/jvm/java-17-openjdk-amd64/bin/keytool`    |


Available Kafka bin commands can also be found with:
```
snap info charmed-kafka --channel 3/stable
```