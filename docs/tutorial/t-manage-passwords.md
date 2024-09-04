This is part of the [Charmed Kafka Tutorial](/t/charmed-kafka-tutorial-overview/10571). Please refer to this page for more information and the overview of the content.

## Manage passwords

Passwords help to secure our cluster and are essential for security. Over time it is a good practice to change the password frequently. Here we will go through setting and changing the password both for the admin user and external Kafka users managed by the data-integrator.

### Admin user

The admin user password management is handled directing by the charm, by using Juju actions. 

#### Retrieve the admin password

As previously mentioned, the admin password can be retrieved by running the `get-admin-credentials` action on the Charmed Kafka application:

```shell
juju run kafka/leader get-admin-credentials
```

Running the command should output:

```yaml
unit-kafka-1:
  UnitId: kafka/1
  id: "10"
  results:
    client-properties: |-
      security.protocol=SASL_PLAINTEXT
      sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="admin" password="e2sMfYLQg7sbbBMFTx1qlaZQKTUxr09x";
      sasl.mechanism=SCRAM-SHA-512
      bootstrap.servers=10.244.26.6:9092,10.244.26.19:9092,10.244.26.43:9092
    password: e2sMfYLQg7sbbBMFTx1qlaZQKTUxr09x
    username: admin
  status: completed
  timing:
    completed: 2023-04-25 12:49:30 +0000 UTC
    enqueued: 2023-04-25 12:49:27 +0000 UTC
    started: 2023-04-25 12:49:28 +0000 UTC
```

The admin password is under the result: `password`.

#### Rotate the admin password

You can change the admin password to a new random password by entering:

```shell
juju run kafka/leader set-password username=admin
```

Running the command should output:

```yaml
unit-kafka-1:
  UnitId: kafka/1
  id: "12"
  results:
    admin-password: zOLGmA1OENYu4REYYJT0OvC6a00lIodg
  status: completed
  timing:
    completed: 2023-04-25 12:51:57 +0000 UTC
    enqueued: 2023-04-25 12:51:35 +0000 UTC
    started: 2023-04-25 12:51:36 +0000 UTC
```

The admin password is under the result: `admin-password`. It should be different from your previous password.

> **Note** When changing the admin password you will also need to update the admin password the in Kafka connection parameters; as the old password will no longer be valid.*

#### Set the admin password

You can change the admin password to a specific password by entering:

```shell
juju run kafka/leader set-password username=admin password=<password>
```

Running the command should output:

```yaml
unit-kafka-1:
  UnitId: kafka/1
  id: "16"
  results:
    admin-password: <password>
  status: completed
  timing:
    completed: 2023-04-25 12:57:45 +0000 UTC
    enqueued: 2023-04-25 12:57:37 +0000 UTC
    started: 2023-04-25 12:57:38 +0000 UTC
```

The admin password under the result: `admin-password` should match whatever you passed in when you entered the command.

> **Note** When changing the admin password you will also need to update the admin password in the Kafka connection parameters, as the old password will no longer be valid.*

### External Kafka users

Unlike Admin management, the password management for external Kafka users is instead managed using relations. Let's see this into play with the Data Integrator charm, that we have deployed in the previous part of the tutorial.

#### Retrieve the password

Similarly to the Kafka application, also the `data-integrator` exposes an action to retrieve the credentials, e.g. 

```shell
juju run data-integrator/leader get-credentials
```

Running the command should output:

```shell 
kafka:
  endpoints: 10.244.26.43:9092,10.244.26.6:9092,10.244.26.19:9092
  password: S4IeRaYaiiq0tsM7m2UZuP2mSI573IGV
  tls: disabled
  topic: test-topic
  username: relation-6
  zookeeper-uris: 10.244.26.121:2181,10.244.26.129:2181,10.244.26.174:2181,10.244.26.251:2181,10.244.26.28:2181/kafka
ok: "True"
```

As before, the admin password is under the result: `password`.

#### Rotate the password

The easiest way to rotate user credentials using the `data-integrator` is by removing and then re-relating the `data-integrator` with the `kafka` charm

```shell
juju remove-relation kafka data-integrator
# wait for the relation to be torn down 
juju relate kafka data-integrator
```

The successful credential rotation can be confirmed by retrieving the new password with the action `get-credentials`

```shell
juju run data-integrator/leader get-credentials 
```

Running the command should now output a different password:

```shell 
kafka:
  endpoints: 10.244.26.43:9092,10.244.26.6:9092,10.244.26.19:9092
  password: ToVfqYQ7tWmNmjy2tJTqulZHmJxJqQ22
  tls: disabled
  topic: test-topic
  username: relation-11
  zookeeper-uris: 10.244.26.121:2181,10.244.26.129:2181,10.244.26.174:2181,10.244.26.251:2181,10.244.26.28:2181/kafka
ok: "True"
```

To rotate external passwords with no or limited downtime, please refer to the how-to guide on [app management](/t/charmed-kafka-how-to-manage-app/10285).

#### Remove the user

To remove the user, remove the relation. Removing the relation automatically removes the user that was created when the relation was created. Enter the following to remove the relation:
```shell
juju remove-relation kafka data-integrator
```

The output of the Juju model should be something like this:

```shell
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  3.1.6    unsupported  10:20:59Z

App              Version  Status   Scale  Charm            Channel      Rev  Exposed  Message
data-integrator           blocked      1  data-integrator  stable        11  no       Please relate the data-integrator with the desired product
kafka                     active       3  kafka            3/stable     147  no       
zookeeper                 active       5  zookeeper        3/stable     114  no       

Unit                Workload  Agent  Machine  Public address  Ports  Message
data-integrator/0*  blocked   idle   8        10.244.26.4            Please relate the data-integrator with the desired product
kafka/0             active    idle   5        10.244.26.43           
kafka/1*            active    idle   6        10.244.26.6            
kafka/2             active    idle   7        10.244.26.19           
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

> **Note** The operations above would also apply to charmed applications that implement the `kafka_client` relation, for which password rotation and user deletion can be achieved in the same consistent way.

## What's next?

In the next part, we will now see how easy it is to enable encryption across the board, to make sure no one is eavesdropping, sniffing or snooping your traffic by enabling TLS.