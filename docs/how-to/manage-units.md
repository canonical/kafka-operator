(how-to-manage-units)=
# How to manage units

For general Juju unit management process, see the [Juju documentation](https://juju.is/docs/juju/manage-units).

(how-to-scaling)=
## Scaling

```{note}
Scaling a Charmed Apache Kafka K8s cluster does not automatically rebalance existing topics and partitions. Rebalancing must be performed manually—before scaling in or after scaling out.
```

```{caution}
Reassign partitions **before** scaling in to ensure that decommissioned units do not hold any data. Failing to do so may lead to data loss.
```

To scale the Charmed Apache Kafka K8s application, use the `juju scale-application` command with the name of the app and the desired number of units:

```shell
juju scale-application kafka-k8s <units>
```

See the `scale-application` [command reference](https://documentation.ubuntu.com/juju/latest/reference/juju-cli/list-of-juju-cli-commands/scale-application/index.html).

Make sure to reassign partitions and topics to use newly added units. See below for guidance.

(how-to-partitions-reassignment)=
### Partition reassignment

When brokers are added or removed, Apache Kafka does not automatically rebalance existing topics and partitions across the new set of brokers.

Without reassignment or rebalancing:

* New storages and new brokers will be used only when new topics and new partitions are created. 
* Removing a broker can result in permanent data loss if the partitions are not replicated on another broker.

Partition reassignment can be done manually by the admin user with the `/opt/kafka/bin/kafka-reassign-partitions.sh` Apache Kafka bin utility script.
For more information on the script usage, refer to [Apache Kafka documentation](https://kafka.apache.org/41/operations/basic-kafka-operations/).

[LinkedIn’s Cruise Control](https://github.com/linkedin/cruise-control) can be used for semi-automatic rebalancing. For guidance on how to use it with Charmed Apache Kafka K8s, see our [Tutorial](tutorial-rebalance-partitions).

## Admin utility scripts

Apache Kafka ships with `bin/*.sh` commands to do various administrative tasks such as:

* `bin/kafka-config.sh` to update cluster configuration
* `bin/kafka-topics.sh` for topic management
* `bin/kafka-acls.sh` for management of ACLs of Apache Kafka users

Please refer to the upstream [Apache Kafka project](https://github.com/apache/kafka/tree/trunk/bin) and its [documentation](https://kafka.apache.org/41/operations/basic-kafka-operations/),
for a full list of the bash commands available in Apache Kafka distributions.
Additionally, you can
use `--help` argument to print a short summary for a given bash command.

These scripts can be found in the `/opt/kafka/bin` folder of the workload container.

```{caution}
Before running bash scripts, make sure that some listeners have been correctly 
opened by creating appropriate integrations. 
```

For more information about listeners opened based on integrations, see the [Listeners](reference-broker-listeners) reference page.
For example, to open a SASL/SCRAM listener, integrate a client application using the data integrator, as described in the [How to manage app guide](how-to-manage-applications).

To run most of the scripts, you need to provide:

1. the Apache Kafka service endpoints, generally referred to as *bootstrap servers*
2. authentication information

### Endpoints and credentials

For Juju admins of the Apache Kafka deployment, the bootstrap servers information can
be obtained using the `get-admin-credentials` action output:

```shell
BOOTSTRAP_SERVERS=$(juju run kafka-k8s/leader get-admin-credentials | grep "bootstrap.servers" | cut -d "=" -f 2)
```

Admin client authentication information is stored in the `/etc/kafka/client.properties` file that is present on every Apache Kafka container.
The content of the file can be accessed using `juju ssh` command:

```shell
juju ssh --container kafka kafka-k8s/leader 'cat /etc/kafka/client.properties'
```

where the `--container kafka` argument selects the Apache Kafka workload container of the unit. By default, the `charm` operator container is opened.

This file can be provided to the Apache Kafka bin commands via the `--command-config`
argument. Note that `client.properties` may also refer to other files (e.g. truststore and keystore for TLS-enabled connections).
Those files also need to be accessible and correctly specified.

Commands can be run within an Apache Kafka broker, since both the authentication
file (along with the truststore if needed) and the Charmed Apache Kafka binaries are
already present. For example, see below.

#### List topics

To list the current topics on the Apache Kafka cluster, using credentials from inside the cluster, run:

```shell
juju ssh --container kafka kafka-k8s/leader '/opt/kafka/bin/kafka-topics.sh --bootstrap-server $BOOTSTRAP_SERVERS --list --command-config /etc/kafka/client.properties'
```

The `BOOTSTRAP_SERVERS` variable contains the information we retrieved earlier in the previous section.

For example, a full command without the usage of the variable might look like the following:

```shell
juju ssh --container kafka kafka-k8s/leader '/opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka-k8s-0.kafka-k8s-endpoints:9092,kafka-k8s-1.kafka-k8s-endpoints:9092,kafka-k8s-2.kafka-k8s-endpoints:9092,kafka-k8s-3.kafka-k8s-endpoints:9092 --list --command-config /etc/kafka/client.properties'
```

where `kafka-k8s-0.kafka-k8s-endpoints:9092,kafka-k8s-1.kafka-k8s-endpoints:9092,kafka-k8s-2.kafka-k8s-endpoints:9092,kafka-k8s-3.kafka-k8s-endpoints:9092` - is the contents of the `$BOOTSTRAP_SERVERS` variable.

### Juju external users

For external users managed by the  [Data Integrator Charm](https://charmhub.io/data-integrator), the endpoints and credentials can be fetched using the dedicated action:

```shell
juju run data-integrator/leader get-credentials --format yaml
```

The `client.properties` file can be generated by substituting the relevant information in the 
file available on the brokers at `/etc/kafka/client.properties`.

To do so, fetch the information using `juju` commands:

```shell
BOOTSTRAP_SERVERS=$(juju run data-integrator/leader get-credentials --format yaml | yq .kafka.endpoints )
USERNAME=$(juju run data-integrator/leader get-credentials --format yaml | yq .kafka.username )
PASSWORD=$(juju run data-integrator/leader get-credentials --format yaml | yq .kafka.password )
```

Then copy the `/etc/kafka/client.properties` and substitute the following lines:

```ini
...
sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="<USERNAME>" password="<PASSWORD>";
...
bootstrap.servers=<BOOTSTRAP_SERVERS>
```
