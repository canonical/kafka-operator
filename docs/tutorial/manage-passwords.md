(tutorial-manage-passwords)=
# 4. Manage passwords

This is a part of the [Charmed Apache Kafka Tutorial](index.md).

## Manage passwords

Passwords help to secure the Apache Kafka cluster and are essential for security. Over time it is a good practice to change the password frequently. Here we will go through setting and changing the password both for the `admin` user and external Charmed Apache Kafka users managed by the `data-integrator`.

### The admin user

The admin user password management is handled directly by the charm, by using Juju actions. 

#### Retrieve the password

As a reminder, the `admin` password is stored in a Juju secret that was created and managed by the Charmed Apache Kafka application.

Get the current value of the `admin` user password from the secret with following:

```shell
juju show-secret --reveal cluster.kafka.app | yq '.. | ."admin-password"? // empty' | tr -d '"'
```

#### Change the password

You can change the admin password to a new password by creating a new Juju secret, and updating the Charmed Apache Kafka application of the correct secret to use.

First, create the Juju secret with the new password you wish to use:

```shell
juju add-secret internal-kafka-users admin=mynewpassword
```

Note the generated secret ID that you see as a response. It will look something like `secret:d2lkl00co3bs3dacm300`.

Now, grant Charmed Apache Kafka access to the new secret:

```shell
juju grant-secret internal-kafka-users kafka
```

Finally, inform Charmed Apache Kafka of the new secret to use for it's internal system users using the secret ID saved earlier:

```shell
juju config kafka system-users=secret:d2lkl00co3bs3dacm300
```

Now, Charmed Apache Kafka will be able to read the new `admin` password from the correct secret, and will proceed to apply the new password on each unit with a rolling-restart of the services with the new configuration.

### External Apache Kafka users

Unlike internal user management of `admin` users, the password management for external Apache Kafka users is instead managed using relations. Let's see this into play with the Data Integrator charm, that we have deployed in the previous part of the tutorial.

#### Retrieve the password

The `data-integrator` exposes an action to retrieve the credentials, e.g: 

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

#### Rotate the password

The easiest way to rotate user credentials using the `data-integrator` is by removing and then re-integrating the `data-integrator` with the `kafka` charm

```shell
juju remove-relation kafka data-integrator

# wait for the relation to be torn down 

juju integrate kafka data-integrator
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

To rotate external passwords with no or limited downtime, please refer to the how-to guide on [app management](how-to-client-connections).

#### Remove the user

To remove the user, remove the relation. Removing the relation automatically removes the user that was created when the relation was created. Enter the following to remove the relation:

```shell
juju remove-relation kafka data-integrator
```

The output of the Juju model should be something like this:

```shell
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  3.6.8    unsupported  23:12:02Z

App              Version  Status   Scale  Charm            Channel        Rev  Exposed  Message
data-integrator           blocked      1  data-integrator  latest/stable  180  no       Please relate the data-integrator with the desired product
kafka            4.0.0    active       3  kafka            4/edge         226  no       
kraft            4.0.0    active       3  kafka            4/edge         226  no       

Unit                Workload  Agent  Machine  Public address  Ports      Message
data-integrator/0*  blocked   idle   6        10.233.204.111             Please relate the data-integrator with the desired product
kafka/0*            active    idle   0        10.233.204.241  19093/tcp  
kafka/1             active    idle   1        10.233.204.196  19093/tcp  
kafka/2             active    idle   2        10.233.204.148  19093/tcp  
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

```{note}
The operations above would also apply to charmed applications that implement the `kafka_client` relation, for which password rotation and user deletion can be achieved in the same consistent way.
```

## What's next?

In the next part, we will now see how easy it is to enable encryption across the board, to make sure no one is eavesdropping, sniffing or snooping your traffic by enabling TLS.

