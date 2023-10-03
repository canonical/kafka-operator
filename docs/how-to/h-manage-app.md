# How to manage related applications

Relations to new applications are supported via the "[kafka_client](https://github.com/canonical/charm-relation-interfaces/blob/main/interfaces/kafka_client/v0/README.md)" interface.

## Within juju via `kafka_client` interface
 
If the charm supports the `kafka_client` interface, just create a relation between the two charms:

```shell
juju relate kafka application
```

To remove a relation:

```shell
juju remove-relation kafka application
```

## Outside juju or for charms not implementing `kafka_client`

The `kafka_client` interface is used with the `data-integrator` charm. This charm allows to automatically create and manage product credentials needed to authenticate with different kinds of data platform charmed products:

Deploy the data-integrator charm with the desired `topic-name` and user roles:
```shell
juju deploy data-integrator --channel edge
juju config data-integrator topic-name=test-topic extra-user-roles=producer,consumer
```

Relate the two applications with:
```shell
juju relate data-integrator kafka
```

To retrieve information, enter:
```shell
juju run-action data-integrator/leader get-credentials --wait
```

This should output something like:
```yaml
unit-data-integrator-0:
  UnitId: data-integrator/0
  id: "4"
  results:
    kafka:
      consumer-group-prefix: relation-27-
      endpoints: 10.123.8.133:19092
      password: ejMp4SblzxkMCF0yUXjaspneflXqcyXK
      tls: disabled
      username: relation-27
      zookeeper-uris: 10.123.8.154:2181,10.123.8.181:2181,10.123.8.61:2181/kafka
    ok: "True"
  status: completed
  timing:
    completed: 2023-01-27 14:22:51 +0000 UTC
    enqueued: 2023-01-27 14:22:50 +0000 UTC
    started: 2023-01-27 14:22:51 +0000 UTC
```

## Password rotation

### External clients

#### With application downtime

The easiest way to rotate user credentials of client applications is by removing and then re-relating 
the application (either a charm supporting the `kafka-client` interface or a `data-integrator`) with the `kafka` charm

```shell
juju remove-relation kafka <charm-or-data-integrator>
# wait for the relation to be torn down 
juju relate kafka <charm-or-data-integrator>
```

The successful credential rotation can be confirmed by retrieving the new password with the action `get-credentials`.

#### Without application downtime

In some use-cases credentials should be rotated with no or limited application downtime.
If credentials should be rotated with no or limited downtine, you can deploy a new charm with the same permissions and resource definition, e.g. 

```shell
juju deploy data-integrator rotated-user --channel stable \
  --config topic-name=test-topic --config extra-user-roles=admin
```

The `data-integrator` charm can then be related to the `kafka` charm to create a new user
```shell
juju relate kafka rotated-user
```

At this point, we effectively have two overlapping users, therefore allowing applications to swap the password
from one to another. 
If the applications consist of fleets of independent producers and consumers, user credentials can be rotated
progressively across fleets, such that no effective downtime is achieved. 

Once all applications have rotated their credentials, it is then safe to remove data first `data-integrator` charm

```shell
juju remove-application data-integrator
```

## Internal Password rotation

The operator user is used internally by the Charmed Kafka Operator, the `set-password` action can be used to rotate its password.
```shell
# to set a specific password for the operator user
juju run-action kafka/leader set-password password=<password> --wait

# to randomly generate a password for the operator user
juju run-action kafka/leader set-password --wait
```