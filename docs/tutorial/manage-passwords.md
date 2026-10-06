(tutorial-manage-passwords)=
# 4. Manage passwords

This is part of the [Charmed Apache Kafka K8s Tutorial](index.md).

Passwords help to secure our cluster and are essential for security. Over time it is a good practice to change the password frequently. Here we will go through setting and changing the password both for the admin user and external Apache Kafka users managed by the data-integrator.

## Admin user

The admin user password management is handled directly by the charm, by using Juju actions.

### Retrieve the admin password

As previously mentioned, the admin password can be retrieved by running the `get-admin-credentials` action on the Charmed Apache Kafka application:

```shell
juju run kafka-k8s/leader get-admin-credentials
```

Running the command should output:

```shell
Running operation 12 with 1 task
  - task 13 on unit-kafka-k8s-2

Waiting for task 13...
client-properties: |-
  sasl.mechanism=SCRAM-SHA-512
  sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="admin" password="0FIQ5QxSaNfl1bXHtV5dyttb21Nbzmpp";
  security.protocol=SASL_PLAINTEXT
  bootstrap.servers=kafka-k8s-2.kafka-k8s-endpoints:9092,kafka-k8s-0.kafka-k8s-endpoints:9092,kafka-k8s-1.kafka-k8s-endpoints:9092
password: 0FIQ5QxSaNfl1bXHtV5dyttb21Nbzmpp
username: admin
```

The admin password is under the result: `password`.

### Rotate the admin password

You can change the admin password to a new random password by entering:

```shell
juju run kafka-k8s/leader set-password username=admin
```

Running the command should output:

```shell
Running operation 14 with 1 task
  - task 15 on unit-kafka-k8s-2

Waiting for task 15...
admin-password: Fz6wPkfGtgjnQ3PCJuZnzJESudZkAvrV
```

The admin password is under the result: `admin-password`. It should be different from your previous password.

```{caution}
When changing the admin password you will also need to update the admin password the in Apache Kafka connection parameters; as the old password will no longer be valid.
```

### Set the admin password

You can change the admin password to a specific password by entering:

```shell
juju run kafka-k8s/leader set-password username=admin password=my-new-password
```

Running the command should output:

```shell
Running operation 18 with 1 task
  - task 19 on unit-kafka-k8s-2

Waiting for task 19...
admin-password: my-new-password
```

The admin password under the result: `admin-password` should match the password we provided as the action argument.

```{caution}
When changing the admin password you will also need to update the admin password the in Apache Kafka connection parameters; as the old password will no longer be valid.
```

## External Apache Kafka users

Unlike Admin management, the password management for external Apache Kafka users is instead managed using relations. Let’s see this into play with the Data Integrator charm, that we have deployed in the previous part of the tutorial.

### Retrieve the password

Similarly to the Charmed Apache Kafka K8s, the `data-integrator` also exposes an action to retrieve the credentials, e.g.:

```shell
juju run data-integrator/leader get-credentials
```

Running the command should output:

```shell
Running operation 22 with 1 task
  - task 23 on unit-data-integrator-0

Waiting for task 23...
kafka:
  endpoints: kafka-k8s-2.kafka-k8s-endpoints:9092,kafka-k8s-1.kafka-k8s-endpoints:9092,kafka-k8s-0.kafka-k8s-endpoints:9092
  password: S4IeRaYaiiq0tsM7m2UZuP2mSI573IGV
  tls: disabled
  topic: test-topic
  username: relation-6
  zookeeper-uris: zookeeper-k8s-0.zookeeper-k8s-endpoints:2181,zookeeper-k8s-1.zookeeper-k8s-endpoints:2181,zookeeper-k8s-2.zookeeper-k8s-endpoints:2181/kafka-k8s
ok: "True"
```

As before, the admin password is under the result: `password`.

### Rotate the password

The easiest way to rotate user credentials using the `data-integrator` is by removing and then re-relating the `data-integrator` with the `kafka-k8s` charm

```shell
juju remove-relation kafka-k8s data-integrator
# wait for the relation to be torn down 
juju integrate kafka-k8s data-integrator
```

The successful credential rotation can be confirmed by retrieving the new password with the action `get-credentials`:

```shell
juju run data-integrator/leader get-credentials
```

Running the command should now output a different password:

```shell
Running operation 24 with 1 task
  - task 25 on unit-data-integrator-0

Waiting for task 25...
kafka:
  endpoints: kafka-k8s-0.kafka-k8s-endpoints:9092,kafka-k8s-1.kafka-k8s-endpoints:9092,kafka-k8s-2.kafka-k8s-endpoints:9092
  password: ToVfqYQ7tWmNmjy2tJTqulZHmJxJqQ22
  tls: disabled
  topic: test-topic
  username: relation-11
  zookeeper-uris: zookeeper-k8s-0.zookeeper-k8s-endpoints:2181,zookeeper-k8s-1.zookeeper-k8s-endpoints:2181,zookeeper-k8s-2.zookeeper-k8s-endpoints:2181/kafka-k8s
ok: "True"
```

To rotate external passwords with no or limited downtime, please refer to the how-to guide on [app management](how-to-manage-applications).

### Remove the user

To remove the user, remove the relation. Removing the relation automatically removes the user that was created when the relation was created. Enter the following to remove the relation:

```shell
juju remove-relation kafka-k8s data-integrator
```

The output of the Juju model should be something like this:

```shell
...
Model     Controller  Cloud/Region        Version  SLA          Timestamp
tutorial  microk8s    microk8s/localhost  3.1.5    unsupported  17:22:21+02:00

App              Version  Status   Scale  Charm            Channel  Rev  Address         Exposed  Message
data-integrator           blocked      1  data-integrator  stable    11  10.152.183.231  no       Please relate the data-integrator with the desired product
kafka-k8s                 active       3  kafka-k8s        3/beta    46  10.152.183.237  no
zookeeper-k8s             active       3  zookeeper-k8s    3/beta    37  10.152.183.134  no

Unit                Workload  Agent  Address     Ports  Message
data-integrator/0*  blocked   idle   10.1.36.42         Please relate the data-integrator with the desired product
kafka-k8s/0         active    idle   10.1.36.78
kafka-k8s/1         active    idle   10.1.36.80
kafka-k8s/2*        active    idle   10.1.36.79
zookeeper-k8s/0     active    idle   10.1.36.84
zookeeper-k8s/1*    active    idle   10.1.36.86
zookeeper-k8s/2     active    idle   10.1.36.85
```

```{note}
The operations above would also apply to Charmed applications that implement  the `kafka_client` relation, for which password rotation and user deletion can be achieved in the same consistent way.
```

## What's next?

In the next part, we will now see how easy it is to enable encryption across the board, to make sure no one is eavesdropping, sniffing or snooping your traffic by enabling TLS.
