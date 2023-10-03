# Manage Passwords

This is part of the [Charmed Kafka Tutorial](/t/charmed-kafka-tutorial-overview/10571). Please refer to this page for more information and the overview of the content.

## Passwords

When we accessed Kafka earlier in this tutorial, we needed to include a password in the connection parameters. 
Passwords help to secure our cluster and are essential for security. Over time it is a good practice to change the password frequently. Here we will go through setting and changing the password for the admin user.

### Retrieve the admin password
As previously mentioned, the admin password can be retrieved by running the `get-admin-credentials` action on the Charmed Kafka application:
```shell
juju run-action kafka/leader get-admin-credentials --wait
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


### Rotate the admin password
You can change the admin password to a new random password by entering:
```shell
juju run-action kafka/leader set-password username=admin --wait
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

*Note when you change the admin password you will also need to update the admin password the in Kafka connection parameters; as the old password will no longer be valid.*

### Set the admin password
You can change the admin password to a specific password by entering:
```shell
juju run-action kafka/leader set-password username=admin password=<password> --wait
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

*Note that when you change the admin password you will also need to update the admin password in the Kafka connection parameters, as the old password will no longer be valid.*

### Kafka Users

As mentioned in the previous section of the Tutorial, the recommended way to create and manage users is by means of the data-integrator charm. 
This will allow us to encode users directly in the Juju model, and - as shown in the following - to rotate user credentials rotations with and without application downtime.   

### Retrieve the password

Similarly to the Kafka application, also the `data-integrator` exposes an action to retrieve the credentials, e.g. 
```shell
juju run-action data-integrator/leader get-credentials --wait
```
Running the command should output:
```shell 
Running operation 22 with 1 task
  - task 23 on unit-data-integrator-0

Waiting for task 23...
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

### Rotate the password

The easiest way to rotate user credentials using the `data-integrator` is by removing and then re-relating the `data-integrator` with the `kafka` charm

```shell
juju remove-relation kafka data-integrator
# wait for the relation to be torn down 
juju relate kafka data-integrator
```

The successful credential rotation can be confirmed by retrieving the new password with the action `get-credentials`

```shell
juju run-action data-integrator/leader get-credentials --wait
```
Running the command should now output a different password:
```shell 
Running operation 24 with 1 task
  - task 25 on unit-data-integrator-0

Waiting for task 25...
kafka:
  endpoints: 10.244.26.43:9092,10.244.26.6:9092,10.244.26.19:9092
  password: ToVfqYQ7tWmNmjy2tJTqulZHmJxJqQ22
  tls: disabled
  topic: test-topic
  username: relation-11
  zookeeper-uris: 10.244.26.121:2181,10.244.26.129:2181,10.244.26.174:2181,10.244.26.251:2181,10.244.26.28:2181/kafka
ok: "True"
```

In order to rotate external password with no or limited downtime, please refer to the how-to guide on [app management](/t/charmed-kafka-how-to-manage-app/10285).