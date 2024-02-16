# How to deploy and manage units

## Basic usage

The Kafka and ZooKeeper operators can both be deployed as follows:
```shell
$ juju deploy zookeeper --channel 3/edge -n 5
$ juju deploy kafka --channel 3/edge -n 3
```

After this, it is necessary to connect them:
```shell
$ juju relate kafka zookeeper
```

To watch the process, `juju status` can be used. Once all the units show as `active|idle` the credentials to access a broker can be queried with:
```shell
juju run kafka/leader get-admin-credentials
```

Apache Kafka ships with `bin/*.sh` commands to do various administrative tasks, e.g `bin/kafka-config.sh` to update cluster configuration, `bin/kafka-topics.sh` for topic management, and many more! The Kafka Charmed Operator provides these commands to administrators to easily run their desired cluster configurations securely with SASL authentication, either from within the cluster or as an external client.

If you wish to run a command from the cluster, in order to (for example) list the current topics on the Kafka cluster, you can run:
```
BOOTSTRAP_SERVERS=$(juju run kafka/leader get-admin-credentials | grep "bootstrap.servers" | cut -d "=" -f 2)
juju ssh kafka/leader 'charmed-kafka.topics --bootstrap-server $BOOTSTRAP_SERVERS --list --command-config /var/snap/charmed-kafka/common/client.properties'
```

Note that when no other application is related to Kafka, the cluster is secured-by-default and listeners are disabled, thus preventing any incoming connection. However, even for running the commands above, listeners must be enable. If there is no other application, deploy a `data-integrator` charm and relate it to Kafka, as outlined in the Relation section to enable listeners.

Available Kafka bin commands can be found with:
```
snap info charmed-kafka --channel 3/edge
```

## Replication

### Scaling up
The charm can be scaled up using `juju add-unit` command.
```shell
juju add-unit kafka
```

To add a specific number of brokers, an extra argument is needed:
```shell
juju add-unit kafka -n <num_brokers_to_add>
```

### Scaling down
To scale down the charm, use `juju remove-unit` command.
```shell
juju remove-unit <unit_name>
```

Even when scaling multiple units at the same time, the charm uses a rolling restart sequence to make sure the cluster stays available and healthy during the operation.