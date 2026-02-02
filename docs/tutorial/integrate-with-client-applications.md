(tutorial-integrate-with-client-applications)=
# 3. Integrate with client applications

This is a part of the [Charmed Apache Kafka Tutorial](index.md).

## Integrate with client applications

As mentioned in the previous section of the Tutorial, the recommended way to create and manage users is by means of another charm: the [Data Integrator Charm](https://charmhub.io/data-integrator). This lets us to encode users directly in the Juju model, and - as shown in the following - rotate user credentials with and without application downtime using relations.

```{note}
Relations, or what Juju documentation describes also as [Integrations](https://documentation.ubuntu.com/juju/3.6/reference/relation/), let two charms to exchange information and interact with one another. Creating a relation between Charmed Apache Kafka and the Data Integrator will automatically generate a username, password, and assign relevant permissions on a given topic. This is the simplest method to create and manage users in Charmed Apache Kafka.
```

### Data Integrator charm

The [Data Integrator charm](https://charmhub.io/data-integrator) is a bare-bones charm for central management of database users, providing support for different kinds of data platforms (e.g. MongoDB, MySQL, PostgreSQL, Apache Kafka, OpenSearch, etc.) with a consistent, opinionated and robust user experience. To deploy the Data Integrator charm we can use the command `juju deploy` we have learned above:

```shell
juju deploy data-integrator --config topic-name=test-topic --config extra-user-roles=producer,consumer
```

The expected output:

```shell
Located charm "data-integrator" in charm-hub, revision 11
Deploying "data-integrator" from charm-hub charm "data-integrator", revision 11 in channel stable on noble
```

### Relate to Charmed Apache Kafka

Now that the Database Integrator charm has been set up, we can relate it to Charmed Apache Kafka. This will automatically create a username, password, and database for the Database Integrator charm. Relate the two applications with:

```shell
juju integrate data-integrator kafka
```

Wait for `watch -n 1 --color juju status --color` to show:

```shell
Model     Controller        Cloud/Region         Version  SLA          Timestamp
tutorial  overlord          localhost/localhost  3.6.8    unsupported  17:00:08Z

App              Version  Status  Scale  Charm            Channel        Rev  Exposed  Message
data-integrator           active      1  data-integrator  latest/stable  180  no       
kafka            4.0.0    active      3  kafka            4/edge         226  no       
kraft            4.0.0    active      3  kafka            4/edge         226  no       

Unit                Workload  Agent  Machine  Public address  Ports           Message
data-integrator/0*  active    idle   6        10.233.204.111                  
kafka/0*            active    idle   0        10.233.204.241  9092,19093/tcp  
kafka/1             active    idle   1        10.233.204.196  9092,19093/tcp  
kafka/2             active    idle   2        10.233.204.148  9092,19093/tcp  
kraft/0             active    idle   3        10.233.204.125  9098/tcp        
kraft/1*            active    idle   4        10.233.204.36   9098/tcp        
kraft/2             active    idle   5        10.233.204.225  9098/tcp        

Machine  State    Address         Inst id        Base          AZ  Message
0        started  10.233.204.241  juju-07a730-0  ubuntu@24.04      Running
1        started  10.233.204.196  juju-07a730-1  ubuntu@24.04      Running
2        started  10.233.204.148  juju-07a730-2  ubuntu@24.04      Running
3        started  10.233.204.125  juju-07a730-3  ubuntu@24.04      Running
4        started  10.233.204.36   juju-07a730-4  ubuntu@24.04      Running
5        started  10.233.204.225  juju-07a730-5  ubuntu@24.04      Running
6        started  10.233.204.111  juju-07a730-6  ubuntu@24.04      Running
```

To retrieve information such as the username, password, and topic. Enter:

```shell
juju run data-integrator/leader get-credentials
```

This should output something like:

```yaml
kafka:
  consumer-group-prefix: relation-9-
  data: '{"extra-user-roles": "producer,consumer", "provided-secrets": "[\"mtls-cert\"]",
    "requested-secrets": "[\"username\", \"password\", \"tls\", \"tls-ca\", \"uris\",
    \"read-only-uris\"]", "topic": "test-topic"}'
  endpoints: 10.233.204.148:9092,10.233.204.196:9092,10.233.204.241:9092
  password: JwxZmIgHIkafm0T6nyPIKbF8m29EALoI
  tls: disabled
  topic: test-topic
  username: relation-9
ok: "True"
```

Make note of the values for `bootstrap-server`, `username` and `password`, we'll be using them later.


### Produce/consume messages

We will now use the username and password to produce some messages to Apache Kafka. To do so, we will first deploy the [Apache Kafka Test App](https://charmhub.io/kafka-test-app): a simplistic charm meant only for testing, that also bundles some Python scripts to push data to Apache Kafka, e.g:

```shell
juju deploy kafka-test-app --channel edge
```

Once the charm is up and running, you can log into the container

```shell
juju ssh kafka-test-app/0 /bin/bash
```

and make sure that the Python virtual environment libraries are visible:

```shell
export PYTHONPATH="/var/lib/juju/agents/unit-kafka-test-app-0/charm/venv:/var/lib/juju/agents/unit-kafka-test-app-0/charm/lib"
```

Once this is set up, you should be able to use the `client.py` script that exposes some functionality to produce and consume messages. 
You can explore the usage of the script

```shell
python3 -m charms.kafka.v0.client --help

usage: client.py [-h] [-t TOPIC] [-u USERNAME] [-p PASSWORD] [-c CONSUMER_GROUP_PREFIX] [-s SERVERS] [-x SECURITY_PROTOCOL] [-n NUM_MESSAGES] [-r REPLICATION_FACTOR] [--num-partitions NUM_PARTITIONS]
                 [--producer] [--consumer] [--cafile-path CAFILE_PATH] [--certfile-path CERTFILE_PATH] [--keyfile-path KEYFILE_PATH] [--mongo-uri MONGO_URI] [--origin ORIGIN]

Handler for running an Apache Kafka client

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

Using this script, you can therefore start producing messages (change the values of `username`, `password` and `bootstrap-servers` to the ones obtained from the `data-integrator` application in the previous section):

```shell
python3 -m charms.kafka.v0.client \
  -u relation-6 \
  -p S4IeRaYaiiq0tsM7m2UZuP2mSI573IGV \
  -t test-topic \
  -s "10.244.26.43:9092,10.244.26.6:9092,10.244.26.19:9092" \
  -n 10 \
  -r 3 \
  --num-partitions 1 \
  --producer \
```

Let this run for a few seconds, then halt the process with `Ctrl+c`.

Now, consume them with:

```shell
python3 -m charms.kafka.v0.client \
  -u relation-6 \
  -p S4IeRaYaiiq0tsM7m2UZuP2mSI573IGV \
  -t test-topic \
  -s "10.244.26.43:9092,10.244.26.6:9092,10.244.26.19:9092" \
  -c "cg" \
  --consumer \
```

Now you know how to use credentials provided by related charms to successfully read/write data from Charmed Apache Kafka!

### Charm client applications

Actually, the Data Integrator is only a very special client charm, that implements the `kafka_client` relation interface for exchanging data with Charmed Apache Kafka and user management via relations. 

For example, the steps above for producing and consuming messages to Apache Kafka have also been implemented in the `kafka-test-app` charm (that also implements the `kafka_client` relation) providing a fully integrated charmed user experience, where producing/consuming messages can simply be achieved using relations.  

#### Producing messages

To produce messages to Apache Kafka, we need to configure the `kafka-test-app` to act as a producer, publishing messages to a specific topic:

```shell
juju config kafka-test-app topic_name=TOP-PICK role=producer num_messages=20
```

To start producing messages to Apache Kafka, we simply relate the Apache Kafka Test App with Apache Kafka:

```shell
juju integrate kafka-test-app kafka
```

```{note}
This will both take care of creating a dedicated user (as was done for the `data-integrator`) as well as start a producer process publishing messages to the `TOP-PICK` topic, basically automating what was done before by hand. 
```

After some time, the `juju status` output should show

```shell
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  3.6.8    unsupported  18:58:47+02:00

App              Version  Status  Scale  Charm            Channel  Rev  Address         Exposed  Message
...
kafka-test-app            active      1  kafka-test-app   edge       8  10.152.183.60   no       Topic TOP-PICK enabled with process producer
...

Unit                Workload  Agent  Address     Ports  Message
...
kafka-test-app/0*   active    idle   10.1.36.88         Topic TOP-PICK enabled with process producer
...
```

announcing that the process has started. To make sure that this is indeed the case, you can check the logs of the process:

```shell
juju exec --application kafka-test-app "tail /tmp/*.log"
```

To stop the process (although it is very likely that the process has already stopped given the low number of messages that were provided) and remove the user, you can just remove the relation:

```shell
juju remove-relation kafka-test-app kafka
```

#### Consuming messages

Note that the `kafka-test-app` charm can also similarly be used to consume messages by changing its configuration to:

```shell
juju config kafka-test-app topic_name=TOP-PICK role=consumer consumer_group_prefix=cg
```

After configuring the Apache Kafka Test App, just relate it again with the Charmed Apache Kafka. This will again create a new user and start the consumer process. 

## What's next?

In the next section, we will learn how to rotate and manage the passwords for the Apache Kafka users, both the admin one and the ones managed by the Data Integrator.

