This is part of the [Charmed Apache Kafka Tutorial](/t/charmed-kafka-tutorial-overview/10571). Please refer to this page for more information and an overview of the content. 

## Deploy Charmed Apache Kafka (and Charmed ZooKeeper)

To deploy Charmed Apache Kafka, all you need to do is run the following commands, which will automatically fetch [Apache Kafka](https://charmhub.io/kafka?channel=3/stable) and [Apache ZooKeeper](https://charmhub.io/zookeeper?channel=3/stable) charms from [Charmhub](https://charmhub.io/) and deploy them to your model. For example, to deploy a cluster of five Apache ZooKeeper units and three Apache Kafka units, you can simply run:

```shell
$ juju deploy zookeeper -n 5
$ juju deploy kafka -n 3 --trust
```

After this, it is necessary to connect them:

```shell
$ juju relate kafka zookeeper
```

Juju will now fetch Charmed Apache Kafka and Apache Zookeeper and begin deploying them to the LXD cloud. This process can take several minutes depending on how provisioned (RAM, CPU, etc) your machine is. You can track the progress by running:

```shell
juju status --watch 1s
```

This command is useful for checking the status of Charmed Apache ZooKeeper and Charmed Apache Kafka and gathering information about the machines hosting the two applications. Some of the helpful information it displays includes IP addresses, ports, state, etc. 
The command updates the status of the cluster every second and as the application starts you can watch the status and messages of Charmed Apache Kafka and Apache ZooKeeper change. 

Wait until the application is ready - when it is ready, `juju status --watch 1s` will show:

```shell
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  3.1.6    unsupported  08:20:12Z

App        Version  Status  Scale  Charm      Channel      Rev  Exposed  Message
kafka               active      3  kafka      3/stable     147  no       
zookeeper           active      5  zookeeper  3/stable     114  no       

Unit          Workload  Agent  Machine  Public address  Ports  Message
kafka/0       active    idle   5        10.244.26.43           machine system settings are not optimal - see logs for info
kafka/1*      active    idle   6        10.244.26.6            machine system settings are not optimal - see logs for info
kafka/2       active    idle   7        10.244.26.19           machine system settings are not optimal - see logs for info
zookeeper/0   active    idle   0        10.244.26.251          
zookeeper/1   active    idle   1        10.244.26.129          
zookeeper/2   active    idle   2        10.244.26.121          
zookeeper/3*  active    idle   3        10.244.26.28           
zookeeper/4   active    idle   4        10.244.26.174          

Machine  State    Address        Inst id        Series  AZ  Message
0        started  10.244.26.251  juju-f1a2cd-0  jammy       Running
1        started  10.244.26.129  juju-f1a2cd-1  jammy       Running
2        started  10.244.26.121  juju-f1a2cd-2  jammy       Running
3        started  10.244.26.28   juju-f1a2cd-3  jammy       Running
4        started  10.244.26.174  juju-f1a2cd-4  jammy       Running
5        started  10.244.26.43   juju-f1a2cd-5  jammy       Running
6        started  10.244.26.6    juju-f1a2cd-6  jammy       Running
7        started  10.244.26.19   juju-f1a2cd-7  jammy       Running
```

To exit the screen with `juju status --watch 1s`, enter `Ctrl+c`.

## Access Apache Kafka cluster

To watch the process, `juju status` can be used. Once all the units show as `active|idle` the credentials to access a broker can be queried with:

```shell
juju run kafka/leader get-admin-credentials
```

The output of the previous command is something like this:

```shell
client-properties: |-
  sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="admin" password="e2sMfYLQg7sbbBMFTx1qlaZQKTUxr09x";
  bootstrap.servers=10.244.26.19:9092,10.244.26.6:9092,10.244.26.43:9092
  security.protocol=SASL_PLAINTEXT
  sasl.mechanism=SCRAM-SHA-512
password: e2sMfYLQg7sbbBMFTx1qlaZQKTUxr09x
username: admin
```

Providing you the `username` and `password` of the Apache Kafka cluster admin user. 

[note type="caution"]
When no other application is related to Apache Kafka, the cluster is secured-by-default and external listeners (bound to port `9092`) are disabled, thus preventing any external incoming connection. 
[/note]

Nevertheless, it is still possible to run a command from within the Apache Kafka cluster using the internal listeners in place of the external ones. 
The internal endpoints can be constructed by replacing the `19092` port in the `bootstrap.servers` returned in the output above, for example:

```shell
INTERNAL_LISTENERS=$(juju run kafka/leader get-admin-credentials | grep "bootstrap.servers" | cut -d "=" -f2 | sed -s "s/\:9092/:19092/g")
```

Once you have fetched the `INTERNAL_LISTENERS`, log in to one of the Kafka containers in one of the units:

```shell
juju ssh kafka/leader sudo -i
```

When the unit is started, the Charmed Apache Kafka Operator installs the [`charmed-kafka`](https://snapcraft.io/charmed-kafka) Snap in the unit that provides a number of entrypoints (that corresponds to the bin commands in the Apache Kafka distribution) for performing various administrative tasks, e.g `charmed-kafka.config` to update cluster configuration, `charmed-kafka.topics` for topic management, and many more! 
Within the machine, the Charmed Apache Kafka Operator also creates a `client.properties` file that already provides the relevant settings to connect to the cluster using the CLI

```shell
CLIENT_PROPERTIES=/var/snap/charmed-kafka/current/etc/kafka/client.properties
```

For example, in order to create a topic, you can run:

```shell
charmed-kafka.topics \
    --create --topic test_topic \
    --bootstrap-server $INTERNAL_LISTENERS \
    --command-config $CLIENT_PROPERTIES
```

You can similarly then list the topic, using:

```shell
charmed-kafka.topics \
    --list \
    --bootstrap-server  $INTERNAL_LISTENERS \
    --command-config $CLIENT_PROPERTIES
```

making sure the topic was successfully created.

You can finally delete the topic, using:

```shell
charmed-kafka.topics \
    --delete --topic test_topic \
    --bootstrap-server  $INTERNAL_LISTENERS \
    --command-config $CLIENT_PROPERTIES
```

Other available Apache Kafka bin commands can also be found with:

```shell
snap info charmed-kafka
```

## What's next?

However, although the commands above can run within the cluster, it is generally recommended during operations
to enable external listeners and use these for running the admin commands from outside the cluster. 
To do so, as we will see in the next section, we will deploy a [data-integrator](https://charmhub.io/data-integrator) charm and relate it to Apache Kafka.