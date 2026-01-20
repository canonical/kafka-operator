(tutorial-integrate-with-client-applications)=
# 3. Integrate with client applications

This is a part of the [Charmed Apache Kafka Tutorial](index.md).

As mentioned in the previous section of the Tutorial, the recommended way to create and manage users is by means of another charm: the [Data Integrator Charm](https://charmhub.io/data-integrator). This lets us to encode users directly in the Juju model, and - as shown in the following - rotate user credentials with and without application downtime using relations.

```{note}
Relations, or what Juju documentation describes also as [Integrations](https://documentation.ubuntu.com/juju/3.6/reference/relation/), let two charms to exchange information and interact with one another. Creating a relation between Charmed Apache Kafka and the Data Integrator will automatically generate a username, password, and assign relevant permissions on a given topic. This is the simplest method to create and manage users in Charmed Apache Kafka.
```

## Data Integrator charm

The [Data Integrator charm](https://charmhub.io/data-integrator) is a bare-bones charm for central management of database users, providing support for different kinds of data platforms (e.g. MongoDB, MySQL, PostgreSQL, Apache Kafka, OpenSearch, etc.) with a consistent, opinionated and robust user experience. To deploy the Data Integrator charm we can use the command `juju deploy` we have learned above:

```shell
juju deploy data-integrator --config topic-name=test-topic --config extra-user-roles=producer,consumer
```

<details> <summary> Output example</summary>

```shell
Deployed "data-integrator" from charm-hub charm "data-integrator", revision 180 in channel latest/stable on ubuntu@24.04/stable
```

</details>

To automatically create a username, password, and database for the Database Integrator charm,
integrate it to the Charmed Apache Kafka:

```shell
juju integrate data-integrator kafka
```

Wait for the status to become `active`/`idle` with the
`watch juju status --color` command.

<details> <summary> Output example</summary>

```shell
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  3.6.13   unsupported  12:50:51Z

App              Version  Status  Scale  Charm            Channel        Rev  Exposed  Message
data-integrator           active      1  data-integrator  latest/stable  180  no       
kafka            4.0.0    active      3  kafka            4/edge         245  no       
kraft            4.0.0    active      3  kafka            4/edge         245  no       

Unit                Workload  Agent      Machine  Public address  Ports           Message
data-integrator/0*  active    idle       6        10.109.154.254                  
kafka/0*            active    executing  0        10.109.154.47   9092,19093/tcp  
kafka/1             active    idle       1        10.109.154.171  9092,19093/tcp  
kafka/2             active    idle       2        10.109.154.82   9092,19093/tcp  
kraft/0*            active    idle       3        10.109.154.49   9098/tcp        
kraft/1             active    idle       4        10.109.154.148  9098/tcp        
kraft/2             active    idle       5        10.109.154.50   9098/tcp        

Machine  State    Address         Inst id        Base          AZ   Message
0        started  10.109.154.47   juju-030538-0  ubuntu@24.04  dev  Running
1        started  10.109.154.171  juju-030538-1  ubuntu@24.04  dev  Running
2        started  10.109.154.82   juju-030538-2  ubuntu@24.04  dev  Running
3        started  10.109.154.49   juju-030538-3  ubuntu@24.04  dev  Running
4        started  10.109.154.148  juju-030538-4  ubuntu@24.04  dev  Running
5        started  10.109.154.50   juju-030538-5  ubuntu@24.04  dev  Running
6        started  10.109.154.254  juju-030538-6  ubuntu@24.04  dev  Running
```

</details>

After the integration is all set, try retrieving credentials such as the username,
password, and topic:

```shell
juju run data-integrator/leader get-credentials
```

This should output something like:

```yaml
Running operation 1 with 1 task
  - task 2 on unit-data-integrator-0

Waiting for task 2...
kafka:
  consumer-group-prefix: relation-8-
  data: '{"resource": "test-topic", "salt": "92Lgizh3GIHxOqTr", "extra-user-roles":
    "producer,consumer", "provided-secrets": ["mtls-cert"], "requested-secrets": ["username",
    "password", "tls", "tls-ca", "uris", "read-only-uris"]}'
  endpoints: 10.109.154.171:9092,10.109.154.47:9092,10.109.154.82:9092
  password: Pw5UJtv1dcOkQzN47qVQNYNSsajeMD5Q
  resource: test-topic
  salt: kAh9cPhs7LnU9OBv
  tls: disabled
  topic: test-topic
  username: relation-8
  version: v0
ok: "True"
```

Make note of the values for `endpoints`, `username` and `password`, we'll be using them later.

## Non-charmed applications

We will now use the username and password to produce some messages to Apache Kafka.
To do so, we will first deploy the [Apache Kafka Test App](https://charmhub.io/kafka-test-app):
a simplistic charm meant only for testing, that also bundles some Python scripts to push data
to Apache Kafka:

```shell
juju deploy kafka-test-app --channel edge
```

Wait for the charm to become `active`/`idle`, and log into the container:

```shell
juju ssh kafka-test-app/0 /bin/bash
```

Make sure that the Python virtual environment libraries are visible:

```shell
export PYTHONPATH="/var/lib/juju/agents/unit-kafka-test-app-0/charm/venv:/var/lib/juju/agents/unit-kafka-test-app-0/charm/lib"
```

Once this is set up, you can use the `client.py` script that exposes some functionality to produce and consume messages.

Let's try that script runs:

```shell
python3 -m charms.kafka.v0.client --help
```

<details> <summary> Output example</summary>

```text
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

</details>

Now let's try producing and then consuming some messages.

Change the values of `username`, `password` and `endpoints` to the ones obtained
from the `data-integrator` application in the previous section and run the script
to produce message:

```shell
python3 -m charms.kafka.v0.client \
  -u <username> \
  -p <password> \
  -t test-topic \
  -s "<endpoints>" \
  -n 10 \
  -r 3 \
  --num-partitions 1 \
  --producer
```

Let this run for a few seconds, then halt the process by pushing `Ctrl+C`.

Now, consume them with:

```shell
python3 -m charms.kafka.v0.client \
  -u <username> \
  -p <password> \
  -t test-topic \
  -s "<endpoints>" \
  --consumer
```

After a few seconds, all previously produced messaged will be consumed, showed in the output,
but the script will continue indefinitely waiting for more.
Since we know that no more messages will be produced now, we can stop the script with `Ctrl+C`.

Now you know how to use credentials provided by related charms to successfully read/write data
from Charmed Apache Kafka!

## Charmed applications

The Data Integrator is a very special client charm,
that implements the `kafka_client` relation interface for exchanging data with
Charmed Apache Kafka and user management via relations.

For example, the steps above for producing and consuming messages to Apache Kafka
have also been implemented in the `kafka-test-app` charm (that also implements
the `kafka_client` relation) providing a fully integrated charmed user experience,
where producing/consuming messages can simply be achieved using relations.  

### Producing messages

To produce messages to Apache Kafka, we need to configure the `kafka-test-app`
to act as a producer, publishing messages to a specific topic:

```shell
juju config kafka-test-app topic_name=TOP-PICK role=producer num_messages=20
```

To start producing messages to Apache Kafka, we simply integrate the Apache Kafka Test App
with Apache Kafka:

```shell
juju integrate kafka-test-app kafka
```

```{note}
This will both take care of creating a dedicated user (as was done for the `data-integrator`)
as well as start a producer process publishing messages to the `TOP-PICK` topic,
basically automating what was done before by hand. 
```

After some time, check the status:

```shell
juju status
```

<details> <summary> Output example</summary>

```shell
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  3.6.13   unsupported  14:27:10Z

App              Version  Status  Scale  Charm            Channel        Rev  Exposed  Message
data-integrator           active      1  data-integrator  latest/stable  180  no       
kafka            4.0.0    active      3  kafka            4/edge         245  no       
kafka-test-app            active      1  kafka-test-app   latest/edge     15  no       Topic TOP-PICK enabled with process producer
kraft            4.0.0    active      3  kafka            4/edge         245  no       

Unit                Workload  Agent      Machine  Public address  Ports           Message
data-integrator/0*  active    idle       6        10.109.154.254                  
kafka-test-app/0*   active    idle       7        10.109.154.242                  Topic TOP-PICK enabled with process producer
kafka/0*            active    executing  0        10.109.154.47   9092,19093/tcp  
kafka/1             active    idle       1        10.109.154.171  9092,19093/tcp  
kafka/2             active    idle       2        10.109.154.82   9092,19093/tcp  
kraft/0*            active    idle       3        10.109.154.49   9098/tcp        
kraft/1             active    idle       4        10.109.154.148  9098/tcp        
kraft/2             active    idle       5        10.109.154.50   9098/tcp        

Machine  State    Address         Inst id        Base          AZ   Message
0        started  10.109.154.47   juju-030538-0  ubuntu@24.04  dev  Running
1        started  10.109.154.171  juju-030538-1  ubuntu@24.04  dev  Running
2        started  10.109.154.82   juju-030538-2  ubuntu@24.04  dev  Running
3        started  10.109.154.49   juju-030538-3  ubuntu@24.04  dev  Running
4        started  10.109.154.148  juju-030538-4  ubuntu@24.04  dev  Running
5        started  10.109.154.50   juju-030538-5  ubuntu@24.04  dev  Running
6        started  10.109.154.254  juju-030538-6  ubuntu@24.04  dev  Running
7        started  10.109.154.242  juju-030538-7  ubuntu@22.04  dev  Running
```

</details>

To make sure that the process has started, check the logs of the process:

```shell
juju exec --application kafka-test-app "tail /tmp/*.log"
```

Make sure to see the following messages:

```text
INFO [__main__] (MainThread) (produce_message) Message published to topic=TOP-PICK, message content: {"timestamp": 1768919219.744478, "_id": "9f4da8c1df2547f18c4d3365f7fb1c54", "origin": "juju-030538-7 (10.109.154.242)", "content": "Message #11"}
```

To stop the process (although it is very likely that the process has already stopped
given the low number of messages that were provided) and remove the user,
you can just remove the relation:

```shell
juju remove-relation kafka-test-app kafka
```

### Consuming messages

The `kafka-test-app` charm can be used to consume messages by changing its configuration:

```shell
juju config kafka-test-app topic_name=TOP-PICK role=consumer consumer_group_prefix=cg
```

After configuring the Apache Kafka Test App, just relate it again with the Charmed Apache Kafka.

```shell
juju integrate kafka-test-app kafka
```

This will again create a new user and start the consumer process.
You can check progress with `juju status`.

Wait for everything to be `active` and `idle` again.
Now you can remove the relation and the entire `kafka-test-app` application entirely
as we won't need them anymore.

```shell
juju remove-relation kafka-test-app kafka
juju remove-application kafka-test-app --destroy-storage
```

## What's next?

In the next section, we will learn how to rotate and manage the passwords for the Apache Kafka users, both the admin one and the ones managed by the Data Integrator.
