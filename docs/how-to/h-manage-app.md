# How to manage related applications

Relations to new applications are supported via the "[mysql_client](https://github.com/canonical/charm-relation-interfaces/blob/main/interfaces/kafka_client/v0/README.md)" interface.

## Within juju via `kafka_client` interface
 
If the charms supports the `kafka_client` interface, just create a relation between the two charms:

```shell
juju relate mysql application
```

To remove a relation:

```shell
juju remove-relation mysql application
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

## Internal Password rotation

The operator user is used internally by the Charmed Kafka Operator, the `set-password` action can be used to rotate its password.
```shell
# to set a specific password for the operator user
juju run-action kafka/leader set-password password=<password> --wait

# to randomly generate a password for the operator user
juju run-action kafka/leader set-password --wait
```