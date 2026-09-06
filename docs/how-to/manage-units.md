---
myst:
  html_meta:
    description: "Scale Charmed Apache Kafka clusters - add or remove broker units and reassign partitions for optimal resource utilization."
---

(how-to-manage-units)=
# How to manage units

For general Juju unit management process, see the [Juju documentation](https://canonical.com/juju/docs/juju-cli/3.6/howto/manage-units/).

## Scaling

```{note}
Scaling a Charmed Apache Kafka cluster does not automatically rebalance existing topics and partitions. Rebalancing must be performed manually—before scaling in or after scaling out.
```

### Add units

To scale-out Charmed Apache Kafka application, add more units:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```shell
juju add-unit kafka -n <num_brokers_to_add>
```

See the `juju add-unit` [command reference](https://canonical.com/juju/docs/juju-cli/latest/reference/juju-cli/list-of-juju-cli-commands/add-unit/).

````

````{tab-item} K8s
:sync: k8s

```shell
juju scale-application kafka-k8s <desired-units>
```

See the `juju scale-application` [command reference](https://documentation.ubuntu.com/juju/latest/reference/juju-cli/list-of-juju-cli-commands/scale-application/index.html).

````

`````

Make sure to reassign partitions and topics to use newly added units. See below for guidance.

### Remove units

```{caution}
Reassign partitions **before** scaling in to ensure that decommissioned units do not hold any data. Failing to do so may lead to data loss.
```

To decrease the number of Apache Kafka brokers, remove some existing units from the Charmed Apache Kafka application:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```shell
juju remove-unit kafka/1 kafka/2
```

See the `juju remove-unit` [command reference](https://canonical.com/juju/docs/juju-cli/latest/reference/juju-cli/list-of-juju-cli-commands/remove-unit/).

````

````{tab-item} K8s
:sync: k8s

```shell
juju scale-application kafka-k8s <desired-units>
```

````

`````

### Partition reassignment

When brokers are added or removed, Apache Kafka does not automatically rebalance existing topics and partitions across the new set of brokers.

Without reassignment or rebalancing:

* New storages and new brokers will be used only when new topics and new partitions are created. 
* Removing a broker can result in permanent data loss if the partitions are not replicated on another broker.

Partition reassignment can still be done manually by the admin user with the
Apache Kafka reassignment utility.

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

Use the `charmed-kafka.reassign-partitions` snap command.

````

````{tab-item} K8s
:sync: k8s

Use `/opt/kafka/bin/kafka-reassign-partitions.sh` in the `kafka` workload
container.

````

`````

For more information on the script usage, refer to [Apache Kafka documentation](https://kafka.apache.org/41/operations/basic-kafka-operations/). 

[LinkedIn’s Cruise Control](https://github.com/linkedin/cruise-control) can be
used for semi-automatic rebalancing. The [partition rebalancing tutorial](tutorial-rebalance-partitions)
demonstrates the workflow for VM deployments; use the same charm actions with
the `kafka-k8s` application on Kubernetes.

## Admin utility scripts

Apache Kafka ships with `bin/*.sh` commands to do various administrative tasks such as:

* `bin/kafka-configs.sh` to update cluster configuration
* `bin/kafka-topics.sh` for topic management
* `bin/kafka-acls.sh` for management of ACLs of Apache Kafka users

Please refer to the upstream [Apache Kafka project](https://github.com/apache/kafka/tree/trunk/bin) and its [documentation](https://kafka.apache.org/41/operations/basic-kafka-operations/),
for a full list of the bash commands available in Apache Kafka distributions.
Additionally, you can use `--help` argument to print a short summary for a given bash command.

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

The most important commands are also exposed via the [Charmed Apache Kafka snap](https://snapcraft.io/charmed-kafka),
accessible via `charmed-kafka.<command>`.
For the mapping between machine snap entry points and Kubernetes executables,
see the [command-line utilities](reference-cli-utilities) reference page.

````

````{tab-item} K8s
:sync: k8s

The scripts are available in `/opt/kafka/bin` inside the `kafka` workload
container. Use `juju ssh --container kafka` to run them.

````

`````

```{caution}
Before running bash scripts, make sure that some listeners have been correctly 
opened by creating appropriate integrations. 
```

For more information about how listeners are opened based on relations, see the [Listeners](reference-broker-listeners).
For example, to open a SASL/SCRAM listener, integrate a client application using the data integrator, as described in the [How to manage client connections](how-to-client-connections) guide.

To run most of the scripts, you need to provide:

1. the Apache Kafka service endpoints, generally referred to as *bootstrap servers*
2. authentication information

### Endpoints and credentials

For Juju admins of the Apache Kafka deployment, the bootstrap servers information can
be obtained using:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```shell
BOOTSTRAP_SERVERS=$(juju run kafka/leader get-admin-credentials | grep "bootstrap.servers" | cut -d "=" -f 2)
```

Admin client authentication information is stored in the
`/var/snap/charmed-kafka/current/etc/kafka/client.properties` file that is present on every Apache Kafka broker.
The content of the file can be accessed using `juju ssh` command:

```shell
juju ssh kafka/leader 'cat /var/snap/charmed-kafka/current/etc/kafka/client.properties'
```

````

````{tab-item} K8s
:sync: k8s

Use the `get-listeners` action and select the advertised address for the client
listener you intend to use:

```shell
juju run kafka-k8s/leader get-listeners
```

Admin client authentication information is stored in
`/etc/kafka/client.properties` in each broker's workload container:

```shell
juju ssh --container kafka kafka-k8s/leader 'cat /etc/kafka/client.properties'
```

````

`````

This file can be provided to the Apache Kafka bin commands via the `--command-config`
argument. Note that `client.properties` may also refer to other files (e.g. truststore and keystore for TLS-enabled connections).
Those files also need to be accessible and correctly specified.

Commands can also be run within an Apache Kafka broker, since both the authentication
file (along with the truststore if needed) and the Apache Kafka utilities are
already present. For example, see below.

#### List topics

To list the current topics on the Apache Kafka cluster, using credentials from inside the cluster, run:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```shell
juju ssh kafka/leader "charmed-kafka.topics --bootstrap-server $BOOTSTRAP_SERVERS --list --command-config /var/snap/charmed-kafka/current/etc/kafka/client.properties"
```

````

````{tab-item} K8s
:sync: k8s

```shell
juju ssh --container kafka kafka-k8s/leader \
  "/opt/kafka/bin/kafka-topics.sh --bootstrap-server $BOOTSTRAP_SERVERS --list --command-config /etc/kafka/client.properties"
```

````

`````

The `BOOTSTRAP_SERVERS` variable contains the information we retrieved earlier in the previous section.

### Juju external users

For external users managed by the [Data Integrator Charm](https://charmhub.io/data-integrator), the endpoints and credentials can be fetched using the dedicated action

```shell
juju run data-integrator/leader get-credentials --format yaml
```

The `client.properties` file can be generated by substituting the relevant information in the
file available on the brokers:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

`/var/snap/charmed-kafka/current/etc/kafka/client.properties`

````

````{tab-item} K8s
:sync: k8s

`/etc/kafka/client.properties` in the `kafka` workload container.

````

`````

To do so, fetch the information using `juju` commands:

```shell
BOOTSTRAP_SERVERS=$(juju run data-integrator/leader get-credentials --format yaml | yq .kafka.endpoints )
USERNAME=$(juju run data-integrator/leader get-credentials --format yaml | yq .kafka.username )
PASSWORD=$(juju run data-integrator/leader get-credentials --format yaml | yq .kafka.password )
```

Then copy the substrate-specific `client.properties` file and substitute the following lines:

```shell
...
sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="<USERNAME>" password="<PASSWORD>";
...
bootstrap.servers=<BOOTSTRAP_SERVERS>
```
