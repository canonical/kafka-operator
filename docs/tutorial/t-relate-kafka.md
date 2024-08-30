This is part of the [Charmed Kafka Tutorial](/t/charmed-kafka-tutorial-overview/10571). Please refer to this page for more information and the overview of the content. 

## Integrate with client applications

As mentioned in the previous section of the Tutorial, the recommended way to create and manage users is by means of another charm: the [Data Integrator Charm](https://charmhub.io/data-integrator). This lets us to encode users directly in the Juju model, and - as shown in the following - rotate user credentials with and without application downtime using Relations.

> Relations, or what Juju documentation describes also as [Integrations](https://juju.is/docs/sdk/integration), let two charms to exchange information and interact with one another. Creating a relation between Kafka and the Data Integrator will automatically generate a username, password, and assign read/write permissions on a given topic. This is the simplest method to create and manage users in Charmed Kafka.

### Data Integrator charm

The [Data Integrator charm](https://charmhub.io/data-integrator) is a bare-bones charm for central management of database users, providing support for different kinds of data platforms (e.g. MongoDB, MySQL, PostgreSQL, Kafka, OpenSearch, etc.) with a consistent, opinionated and robust user experience. To deploy the Data Integrator charm we can use the command `juju deploy` we have learned above:

```shell
juju deploy data-integrator --channel stable --config topic-name=test-topic --config extra-user-roles=producer,consumer
```

The expected output:

```shell
Located charm "data-integrator" in charm-hub, revision 11
Deploying "data-integrator" from charm-hub charm "data-integrator", revision 11 in channel stable on jammy
```

### Relate to Kafka

Now that the Database Integrator Charm has been set up, we can relate it to Kafka. This will automatically create a username, password, and database for the Database Integrator Charm. Relate the two applications with:

```shell
juju relate data-integrator kafka
```

Wait for `juju status --watch 1s` to show:

```shell
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  3.1.6    unsupported  10:04:50Z

App              Version  Status  Scale  Charm            Channel      Rev  Exposed  Message
data-integrator           active      1  data-integrator  stable        11  no       
kafka                     active      3  kafka            3/stable     147  no       
zookeeper                 active      5  zookeeper        3/stable     114  no       

Unit                Workload  Agent  Machine  Public address  Ports  Message
data-integrator/0*  active    idle   8        10.244.26.4            
kafka/0             active    idle   5        10.244.26.43           machine system settings are not optimal - see logs for info
kafka/1*            active    idle   6        10.244.26.6            machine system settings are not optimal - see logs for info
kafka/2             active    idle   7        10.244.26.19           machine system settings are not optimal - see logs for info
zookeeper/0         active    idle   0        10.244.26.251          
zookeeper/1         active    idle   1        10.244.26.129          
zookeeper/2         active    idle   2        10.244.26.121          
zookeeper/3*        active    idle   3        10.244.26.28           
zookeeper/4         active    idle   4        10.244.26.174          

Machine  State    Address        Inst id        Series  AZ  Message
0        started  10.244.26.251  juju-f1a2cd-0  jammy       Running
1        started  10.244.26.129  juju-f1a2cd-1  jammy       Running
2        started  10.244.26.121  juju-f1a2cd-2  jammy       Running
3        started  10.244.26.28   juju-f1a2cd-3  jammy       Running
4        started  10.244.26.174  juju-f1a2cd-4  jammy       Running
5        started  10.244.26.43   juju-f1a2cd-5  jammy       Running
6        started  10.244.26.6    juju-f1a2cd-6  jammy       Running
7        started  10.244.26.19   juju-f1a2cd-7  jammy       Running
8        started  10.244.26.4    juju-f1a2cd-8  jammy       Running
```

To retrieve information such as the username, password, and topic. Enter:

```shell
juju run data-integrator/leader get-credentials
```

This should output something like:

```yaml
kafka:
  consumer-group-prefix: relation-6-
  endpoints: 10.244.26.43:9092,10.244.26.6:9092,10.244.26.19:9092
  password: ILg8C5msYRvqOnGATeFPyw2DKHncritf
  tls: disabled
  topic: test-topic
  username: relation-6
  zookeeper-uris: 10.244.26.121:2181,10.244.26.129:2181,10.244.26.174:2181,10.244.26.251:2181,10.244.26.28:2181/kafka
ok: "True"
```

Save the value listed under `bootstrap-server`, `username` and `password`. *(Note: your hostnames, usernames, and passwords will likely be different.)*

### Produce/consume messages

We will now use the username and password to produce some messages to Kafka. To do so, we will first deploy the Kafka Test App (available [here](https://charmhub.io/kafka-test-app)): a test charm that also bundles some python scripts to push data to Kafka, e.g.

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

Once this is setup, you should be able to use the `client.py` script that exposes some functionality to produce and consume messages. 
You can explore the usage of the script

```shell
python3 -m charms.kafka.v0.client --help

usage: client.py [-h] [-t TOPIC] [-u USERNAME] [-p PASSWORD] [-c CONSUMER_GROUP_PREFIX] [-s SERVERS] [-x SECURITY_PROTOCOL] [-n NUM_MESSAGES] [-r REPLICATION_FACTOR] [--num-partitions NUM_PARTITIONS]
                 [--producer] [--consumer] [--cafile-path CAFILE_PATH] [--certfile-path CERTFILE_PATH] [--keyfile-path KEYFILE_PATH] [--mongo-uri MONGO_URI] [--origin ORIGIN]

Handler for running a Kafka client

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

Using this script, you can therefore start producing messages (change the values of `username`, `password` and `servers`)

```shell
python3 -m charms.kafka.v0.client \
  -u relation-6 -p S4IeRaYaiiq0tsM7m2UZuP2mSI573IGV \
  -t test-topic \
  -s "10.244.26.43:9092,10.244.26.6:9092,10.244.26.19:9092" \
  -n 10 --producer \
  -r 3 --num-partitions 1
```

and consume them 

```shell
python3 -m charms.kafka.v0.client \
  -u relation-6 -p S4IeRaYaiiq0tsM7m2UZuP2mSI573IGV \
  -t test-topic \
  -s "10.244.26.43:9092,10.244.26.6:9092,10.244.26.19:9092" \
  --consumer \
  -c "cg"
```

### Charm client applications

Actually, the Data Integrator is only a very special client charm, that implements the `kafka_client` relation for exchanging data with the Kafka charm and user management via relations. 

For example, the steps above for producing and consuming messages to Kafka have also been implemented in the `kafka-test-app` charm (that also implement the `kafka_client` relation) providing a fully integrated charmed user-experience, where producing/consuming messages can simply be achieved using relations.  

#### Producing messages

To produce messages to Kafka, we need to configure the `kafka-test-app` to act as a producer, publishing messages to a specific topic:

```shell
juju config kafka-test-app topic_name=test_kafka_app_topic role=producer num_messages=20
```

To start producing messages to Kafka, we **JUST** simply relate the Kafka Test App with Kafka

```shell
juju relate kafka-test-app kafka
```

> **Note**: This will both take care of creating a dedicated user (as much as done for the data-integrator) as well as start a producer process publishing messages to the `test_kafka_app_topic` topic, basically automating what was done before by hands. 

After some time, the `juju status` output should show

```shell
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  3.1.6    unsupported  18:58:47+02:00

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
juju remove-relation kafka-test-app kafka
```

#### Consuming messages

Note that the `kafka-test-app` charm can also similarly be used to consume messages by changing its configuration to

```shell
juju config kafka-test-app topic_name=test_kafka_app_topic role=consumer consumer_group_prefix=cg
```

After configuring the Kafka Test App, just relate it again with the Kafka charm. This will again create a new user and start the consumer process. 

## What's next?

In the next section, we will learn how to rotate and manage the passwords for the Kafka users, both the admin one and the ones managed by the Data Integrator.