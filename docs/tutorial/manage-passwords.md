(tutorial-manage-passwords)=
# 5. Manage passwords

This is a part of the [Charmed Apache Kafka Tutorial](index.md).

## Manage passwords

Passwords help to secure the Apache Kafka cluster and are essential for security. Over time it is a good practice to change the password frequently. Here we will go through setting and changing the password both for the built-in user and external Charmed Apache Kafka users managed by the `data-integrator`.

### The admin user

The admin user password management is handled directly by the charm, by using Juju actions.

#### Retrieve the password

As a reminder, the admin password is stored in a Juju secret that was created and managed by the Charmed Apache Kafka application. The password in in the `operator-password` field.

Get the current value of the admin user password from the secret:

```shell
juju show-secret --reveal cluster.kafka.app | yq -r '.[].content["operator-password"]'
```

#### Change the password

You can change the admin password to a new password by creating a new Juju secret, and updating the Charmed Apache Kafka application of the correct secret to use.

First, create the Juju secret with the new password you wish to use:

```shell
juju add-secret internal-kafka-users admin=mynewpassword
```

Note the generated secret ID that you see as a response.
It will look something like `secret:d5nc29hlshbc45lnf07g`.

Now, grant Charmed Apache Kafka access to the new secret:

```shell
juju grant-secret internal-kafka-users kafka
```

Finally, inform Charmed Apache Kafka of the new secret to use for it's internal system users using the secret ID saved earlier:

```shell
juju config kafka system-users=secret:d5nc29hlshbc45lnf07g
```

Now, Charmed Apache Kafka will be able to read the new admin password from the correct secret, and will proceed to apply the new password on each unit with a rolling-restart of the services with the new configuration.

### External Apache Kafka users

Unlike internal user management of `admin` users, the password management for external Apache Kafka users is instead managed using relations. Let's see this into play with the Data Integrator charm, that we have deployed in the previous part of the tutorial.

#### Retrieve the password

The `data-integrator` exposes an action to retrieve the credentials:

```shell
juju run data-integrator/leader get-credentials
```

<details> <summary> Output example</summary>

Running the command should output:

```shell
Running operation 15 with 1 task
  - task 16 on unit-data-integrator-0

Waiting for task 16...
kafka:
  consumer-group-prefix: relation-8-
  data: '{"resource": "test-topic", "salt": "yOIRb9uVUuJuKFVc", "extra-user-roles":
    "producer,consumer", "provided-secrets": ["mtls-cert"], "requested-secrets": ["username",
    "password", "tls", "tls-ca", "uris", "read-only-uris"]}'
  endpoints: 10.168.161.12:9092,10.168.161.221:9092,10.168.161.6:9092
  password: RdRjZkXUC3dAb5VRFw2470fnoKrsRIXU
  resource: test-topic
  salt: W34UoIPzckdMJ6DU
  tls: disabled
  topic: test-topic
  username: relation-8
  version: v0
ok: "True"
```

</details>

#### Rotate the password

The easiest way to rotate user credentials using the `data-integrator` is by removing and then re-integrating the `data-integrator` with the `kafka` charm:

```shell
juju remove-relation kafka data-integrator
```

Wait for the relation to be torn down and add integration again:

```shell
juju integrate kafka data-integrator
```

The successful credential rotation can be confirmed by retrieving the new password with the action `get-credentials`:

```shell
juju run data-integrator/leader get-credentials 
```

<details> <summary> Output example</summary>

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

</details>

To rotate external passwords with no or limited downtime, please refer to the how-to guide on [app management](how-to-client-connections).

#### Remove the user

To remove the user, remove the relation. Removing the relation automatically removes the user that was created when the relation was created. Enter the following to remove the relation:

```shell
juju remove-relation kafka data-integrator
```

<details> <summary> Output example</summary>

The output of the Juju model should be something like this:

```shell
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  3.6.12   unsupported  23:56:52Z

App              Version  Status   Scale  Charm            Channel        Rev  Exposed  Message
data-integrator           blocked      1  data-integrator  latest/stable  180  no       Please relate the data-integrator with the desired product
kafka            4.0.0    active       3  kafka            4/edge         245  no       
kafka-test-app            active       1  kafka-test-app   latest/edge     15  no       Topic TOP-PICK enabled with process consumer
kraft            4.0.0    active       3  kafka            4/edge         245  no           

Unit                Workload  Agent  Machine  Public address  Ports           Message
data-integrator/0*  blocked   idle   6        10.168.161.107                  Please relate the data-integrator with the desired product
kafka-test-app/0*   active    idle   7        10.168.161.157                  Topic TOP-PICK enabled with process consumer
kafka/0             active    idle   0        10.168.161.221  9092,19093/tcp  
kafka/1*            active    idle   1        10.168.161.6    9092,19093/tcp  
kafka/2             active    idle   2        10.168.161.12   9092,19093/tcp  
kraft/0             active    idle   3        10.168.161.5    9098/tcp        
kraft/1             active    idle   4        10.168.161.212  9098/tcp        
kraft/2*            active    idle   5        10.168.161.33   9098/tcp        

Machine  State    Address         Inst id         Base          AZ   Message
0        started  10.168.161.221  juju-67d727-0   ubuntu@24.04  dev  Running
1        started  10.168.161.6    juju-67d727-1   ubuntu@24.04  dev  Running
2        started  10.168.161.12   juju-67d727-2   ubuntu@24.04  dev  Running
3        started  10.168.161.5    juju-67d727-3   ubuntu@24.04  dev  Running
4        started  10.168.161.212  juju-67d727-4   ubuntu@24.04  dev  Running
5        started  10.168.161.33   juju-67d727-5   ubuntu@24.04  dev  Running
6        started  10.168.161.107  juju-67d727-6   ubuntu@24.04  dev  Running
7        started  10.168.161.157  juju-67d727-7   ubuntu@22.04  dev  Running
```

</details>

```{note}
The operations above would also apply to charmed applications that implement the `kafka_client` relation, for which password rotation and user deletion can be achieved in the same consistent way.
```

## What's next?

In the next part, we will now see how easy it is to enable encryption across the board, to make sure no one is eavesdropping, sniffing or snooping your traffic by enabling TLS.
