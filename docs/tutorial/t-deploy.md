# Get a Charmed Kafka and Zookeeper up and running

This is part of the [Charmed Kafka Tutorial](/t/charmed-kafka-tutorial-overview/10571). Please refer to this page for more information and the overview of the content. 

## Deploy

To deploy Charmed Kafka, all you need to do is run the following commands, which will automatically fetch [Kafka](https://charmhub.io/kafka?channel=3/stable) and [Zookeeper](https://charmhub.io/zookeeper?channel=3/stable) charms from [Charmhub](https://charmhub.io/) and deploy them to your model. For example, to deploy a 5 Zookeeper unit and 3 Kafka unit cluster, you can simply run

```shell
$ juju deploy zookeeper -n 5
$ juju deploy kafka -n 3
```

After this, it is necessary to connect them:

```shell
$ juju relate kafka zookeeper
```

Juju will now fetch Charmed Kafka and Zookeeper and begin deploying it to the LXD cloud. This process can take several minutes depending on how provisioned (RAM, CPU,etc) your machine is. You can track the progress by running:
```shell
juju status --watch 1s
```

This command is useful for checking the status of Charmed Zookeeper and Charmed Kafka and gathering information about the machines hosting the two applications. Some of the helpful information it displays include IP addresses, ports, state, etc. 
The command updates the status of the cluster every second and as the application starts you can watch the status and messages of Charmed Kafka and Zookeeper change. 

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

## Access Kafka cluster

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

Providing you the `username` and `password` of the Kafka cluster admin user. 

> **IMPORTANT** Note that when no other application is related to Kafka, the cluster is secured-by-default and external listeners (binded to port 9092) are disabled, thus preventing any external incoming connection. 

Nevertheless, it is still possible to run a command from within the Kafka cluster using the internal listeners in place of the external ones. 
The internal endpoints can be constructed by replacing the 19092 port in the `bootstrap.servers` returned in the output above, e.g. 

```shell
INTERNAL_LISTENERS=$(juju run kafka/leader get-admin-credentials | grep "bootstrap.servers" | cut -d "=" -f2 | sed -s "s/\:9092/:19092/g")
```

Once you have fetched the `INTERNAL_LISTENERS`, log in into one of the Kafka container in one of the units

```shell
juju ssh kafka/leader sudo -i
```

When the unit is started, the Charmed Kafka Operator installs the [`charmed-kafka`](https://snapcraft.io/charmed-kafka) Snap in the unit that provides a number of entrypoints (that corresponds to the bin commands in the Kafka distribution) for performing various administrative tasks, e.g `charmed-kafka.config` to update cluster configuration, `charmed-kafka.topics` for topic management, and many more! 
Within the machine, the Charmed Kafka Operator also creates a `client.properties` file that already provides the relevant settings to connect to the cluster using the CLI

```shell
CLIENT_PROPERTIES= /var/snap/charmed-kafka/current/etc/kafka/client.properties
```

For example, in order to create a topic, you can run:
```shell
charmed-kafka.topics \
    --create --topic test_topic \
    --bootstrap-server $INTERNAL_LISTENERS \
    --command-config $CLIENT_PROPERTIES
```

You can similarly then list the topic, using
```shell
charmed-kafka.topics \
    --list \
    --bootstrap-server  $INTERNAL_LISTENERS \
    --command-config $CLIENT_PROPERTIES
```

making sure the topic was successfully created.

You can finally delete the topic, using 

```shell
charmed-kafka.topics \
    --delete --topic test_topic \
    --bootstrap-server  $INTERNAL_LISTENERS \
    --command-config $CLIENT_PROPERTIES
```

Other available Kafka bin commands can also be found with:
```shell
snap info charmed-kafka
```

However, although the commands above can run within the cluster, it is generally recommended during operations
to enable external listeners and use these for running the admin commands from outside the cluster. 
To do so, as we will see in the next section, we will deploy a [data-integrator](https://charmhub.io/data-integrator) charm and relate it to Kafka.