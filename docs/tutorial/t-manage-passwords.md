# Manage Passwords

This is part of the [Charmed Kafka Tutorial](https://discourse.charmhub.io/t/charmed-kafka-tutorial/). Please refer to this page for more information and the overview of the content.

## Passwords

When we accessed Kafka earlier in this tutorial, we needed to include a password in the connection parameters. 
Passwords help to secure our cluster and are essential for security. Over time it is a good practice to change the password frequently. Here we will go through setting and changing the password for the admin user.

### Retrieve the admin password
As previously mentioned, the admin password can be retrieved by running the `get-password` action on the Charmed Kafka application:
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