(tutorial-integrate-with-client-applications)=
# 3. Integrate with client applications

This is a part of the [Charmed Apache Kafka K8s Tutorial](index.md).

As mentioned in the previous section of the Tutorial, the recommended way to create and manage users is by means of another charm: the [Data Integrator Charm](https://charmhub.io/data-integrator). This will let us encode users directly in the Juju model, and - as shown in the following - rotate user credentials rotations with and without application downtime using Relations.

```{note}
Relations, or what Juju documentation describes also as [Integrations](https://documentation.ubuntu.com/juju/3.6/reference/relation/), let two charms to exchange information and interact with one another. Creating a relation between Apache Kafka and the Data Integrator will automatically generate a username, password, and assign read/write permissions on a given topic. This is the simplest method to create and manage users in Charmed Apache Kafka K8s.
```

## Data Integrator charm

The [Data Integrator charm](https://charmhub.io/data-integrator) is a bare-bones charm for central management of database users, providing support for different kinds of data platforms (e.g. MongoDB, MySQL, PostgreSQL, Apache Kafka, OpenSearch, etc.) with a consistent, opinionated and robust user experience. To deploy the Data Integrator charm we can use the command `juju deploy` we have learned above:

```shell
juju deploy data-integrator --channel stable --config topic-name=test-topic --config extra-user-roles=producer,consumer
```

## Integrate with Charmed Apache Kafka K8s

Now that the Database Integrator Charm has been set up, we can integrate it with Charmed Apache Kafka K8s. This will automatically create a username, password, and database for the Database Integrator Charm. Integrate the two applications with:

```shell
juju integrate data-integrator kafka-k8s
```

Wait for `watch -c juju status --color` to show:

```shell
Model     Controller  Cloud/Region        Version  SLA          Timestamp
tutorial  microk8s    microk8s/localhost  3.1.5    unsupported  18:18:16+02:00

App              Version  Status  Scale  Charm            Channel  Rev  Address         Exposed  Message
data-integrator           active      1  data-integrator  stable    13  10.152.183.188  no
kafka-k8s                 active      3  kafka-k8s        3/edge    39  10.152.183.237  no
zookeeper-k8s             active      3  zookeeper-k8s    3/edge    33  10.152.183.134  no

Unit                Workload  Agent  Address     Ports  Message
data-integrator/0*  active    idle   10.1.36.87
kafka-k8s/0         active    idle   10.1.36.78
kafka-k8s/1         active    idle   10.1.36.80
kafka-k8s/2*        active    idle   10.1.36.79
zookeeper-k8s/0     active    idle   10.1.36.84
zookeeper-k8s/1*    active    idle   10.1.36.86
zookeeper-k8s/2     active    idle   10.1.36.85
```

To retrieve information such as the username, password, and topic:

```shell
juju run data-integrator/leader get-credentials 
```

This should output something like:

```shell
Running operation 5 with 1 task
  - task 6 on unit-data-integrator-0

Waiting for task 6...
kafka:
  endpoints: kafka-k8s-2.kafka-k8s-endpoints:9092,kafka-k8s-0.kafka-k8s-endpoints:9092,kafka-k8s-1.kafka-k8s-endpoints:9092
  password: S4IeRaYaiiq0tsM7m2UZuP2mSI573IGV
  tls: disabled
  topic: test-topic
  username: relation-6
  zookeeper-uris: zookeeper-k8s-0.zookeeper-k8s-endpoints:2181,zookeeper-k8s-1.zookeeper-k8s-endpoints:2181,zookeeper-k8s-2.zookeeper-k8s-endpoints:2181/kafka-k8s
ok: "True"
```

Save the value listed under `bootstrap-server`, `username` and `password`. *(Note: your hostname, usernames, and passwords will likely be different.)*

## Produce/consume messages

We will now use the username and password to produce some messages to Apache Kafka. To do so, we will first deploy the [Apache Kafka Test App](https://charmhub.io/kafka-test-app): a test charm that also bundles some Python scripts to push data to Apache Kafka, e.g.:

```shell
juju deploy kafka-test-app -n1 --channel edge
```

Once the charm is up and running, you can log into the container

```shell
juju ssh kafka-test-app/0 /bin/bash
```

and make sure that the Python virtual environment libraries are visible:

```shell
export PYTHONPATH="/var/lib/juju/agents/unit-kafka-test-app-0/charm/venv:/var/lib/juju/agents/unit-kafka-test-app-0/charm/lib"
```

Once this is set up, you can use the `client.py` script that exposes some functionality to produce and consume messages. 
You can explore the usage of the script:

```shell
python3 -m charms.kafka.v0.client --help

usage: client.py [-h] [-t TOPIC] [-u USERNAME] [-p PASSWORD] [-c CONSUMER_GROUP_PREFIX] [-s SERVERS] [-x SECURITY_PROTOCOL] [-n NUM_MESSAGES] [-r REPLICATION_FACTOR] [--num-partitions NUM_PARTITIONS]
                 [--producer] [--consumer] [--cafile-path CAFILE_PATH] [--certfile-path CERTFILE_PATH] [--keyfile-path KEYFILE_PATH] [--mongo-uri MONGO_URI] [--origin ORIGIN]

Handler for running a Apache Kafka client

options:
  -h, --help            show this help message and exit
  -t TOPIC, --topic TOPIC
                        Kafka topic provided by Kafka Charm
  -u USERNAME, --username USERNAME
                        Kafka username provided by Kafka Charm
  -p PASSWORD, --password PASSWORD
                        Kafka password provided by Kafka Charm
  -c CONSUMER_GROUP_PREFIX, --consumer-group-prefix CONSUMER_GROUP_PREFIX
                        Kafka consumer-group-prefix provided by Kafka Charm
  -s SERVERS, --servers SERVERS
                        comma delimited list of Kafka bootstrap-server strings
  -x SECURITY_PROTOCOL, --security-protocol SECURITY_PROTOCOL
                        security protocol used for authentication
  -n NUM_MESSAGES, --num-messages NUM_MESSAGES
                        number of messages to send from a producer
  -r REPLICATION_FACTOR, --replication-factor REPLICATION_FACTOR
                        replcation.factor for created topics
  --num-partitions NUM_PARTITIONS
                        partitions for created topics
  --producer
  --consumer
  --cafile-path CAFILE_PATH
  --certfile-path CERTFILE_PATH
  --keyfile-path KEYFILE_PATH
  --mongo-uri MONGO_URI
  --origin ORIGIN
```

Using this script, you can therefore start producing messages:

```shell
python3 -m charms.kafka.v0.client \
  -u relation-6 -p S4IeRaYaiiq0tsM7m2UZuP2mSI573IGV \
  -t test-topic \
  -s "kafka-k8s-2.kafka-k8s-endpoints:9092,kafka-k8s-0.kafka-k8s-endpoints:9092,kafka-k8s-1.kafka-k8s-endpoints:9092" \
  -n 10 --producer \
  -r 3 --num-partitions 1
```

and consume them 

```shell
python3 -m charms.kafka.v0.client \
  -u relation-6 -p S4IeRaYaiiq0tsM7m2UZuP2mSI573IGV \
  -t test-topic \
  -s "kafka-k8s-2.kafka-k8s-endpoints:9092,kafka-k8s-0.kafka-k8s-endpoints:9092,kafka-k8s-1.kafka-k8s-endpoints:9092" \
  --consumer \
  -c "cg"
```

## Charm client applications

Actually, the Data Integrator is only a very special client charm,  that implements the `kafka_client` relation for exchanging data with Charmed Apache Kafka K8s and user management via relations. 

For example, the steps above for producing and consuming messages to Apache Kafka have also been implemented in the `kafka-test-app` charm (that also implements the `kafka_client` relation) providing a fully integrated charmed user experience, where producing/consuming messages can simply be achieved using relations.  

### Producing messages

To produce messages to Apache Kafka, we need to configure the `kafka-test-app` to act as a producer, publishing messages to a specific topic:

```shell
juju config kafka-test-app topic_name=test_kafka_app_topic role=producer num_messages=20
```

To start to produce messages to Apache Kafka, we **JUST** simply integrate the Apache Kafka Test App with `kafka-k8s`:

```shell
juju integrate kafka-test-app kafka-k8s
```

```{note}
This will both take care of creating a dedicated user (as much as done for the data-integrator) as well as start a producer process publishing messages to the `test_kafka_app_topic` topic, basically automating what was done before by hand. 
```

After some time, the `juju status` output should show:

```shell
Model     Controller  Cloud/Region        Version  SLA          Timestamp
tutorial  microk8s    microk8s/localhost  3.1.5    unsupported  18:58:47+02:00

App              Version  Status  Scale  Charm            Channel  Rev  Address         Exposed  Message
...
kafka-test-app            active      1  kafka-test-app   edge       8  10.152.183.60   no       Topic test_kafka_app_topic enabled with process producer
...

Unit                Workload  Agent  Address     Ports  Message
...
kafka-test-app/0*   active    idle   10.1.36.88         Topic test_kafka_app_topic enabled with process producer
...
```

indicating that the process has started. To make sure that this is indeed the case, you can check the logs of the process:

```shell
juju exec --application kafka-test-app "tail /tmp/*.log"
```

To stop the process (although it is very likely that the process has already stopped given the low number of messages that were provided) and remove the user,  you can just remove the relation 

```shell
juju remove-relation kafka-test-app kafka-k8s
```

### Consuming messages

Note that the `kafka-test-app` charm can also similarly be used to consume messages by changing its configuration to

```shell
juju config kafka-test-app topic_name=test_kafka_app_topic role=consumer consumer_group_prefix=cg
```

After configuring the Apache Kafka Test App, just integrate it again with the Charmed Apache Kafka K8s. This will again create a new user and start the consumer process. 

## What's next?

In the next section, we will learn how to rotate and manage the passwords for the Apache Kafka users, both the admin one and the ones managed by the Data Integrator.
