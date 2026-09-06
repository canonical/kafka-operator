---
myst:
  html_meta:
    description: "Manage Charmed Apache Kafka client connections using the kafka_client interface and data-integrator charm for credential management."
---

(how-to-client-connections)=
# How to manage client connections

Relations to new applications are supported via the "[{spellexception}`kafka_client`](https://github.com/canonical/charm-relation-interfaces/blob/main/interfaces/kafka_client/v0/README.md)" interface.

## Via the `kafka_client` charm relation interface

If the charm supports the `kafka_client` relation interface, just create an integration between the two charms:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```shell
juju integrate kafka application
```

````

````{tab-item} K8s
:sync: k8s

```shell
juju integrate kafka-k8s application
```

````

`````

To remove a relation:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```shell
juju remove-relation kafka application
```

````

````{tab-item} K8s
:sync: k8s

```shell
juju remove-relation kafka-k8s application
```

````

`````

## Non-charmed applications and external clients

The `kafka_client` interface is used with the `data-integrator` charm. This charm automatically creates and manages product credentials needed to authenticate with different kinds of data platform charmed products:

Deploy the Data Integrator charm with the desired `topic-name` and user roles:

```shell
juju deploy data-integrator
juju config data-integrator topic-name=test-topic extra-user-roles=producer,consumer
```

Integrate the two applications with:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```shell
juju integrate data-integrator kafka
```

````

````{tab-item} K8s
:sync: k8s

```shell
juju integrate data-integrator kafka-k8s
```

````

`````

To retrieve information, enter:

```shell
juju run data-integrator/leader get-credentials
```

This should output something like:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```yaml
kafka:
  consumer-group-prefix: relation-27-
  endpoints: 10.123.8.133:19092
  password: ejMp4SblzxkMCF0yUXjaspneflXqcyXK
  tls: disabled
  username: relation-27
ok: "True"
```

````

````{tab-item} K8s
:sync: k8s

```yaml
kafka:
  consumer-group-prefix: relation-8-
  endpoints: kafka-k8s-0.kafka-k8s-endpoints:9092,kafka-k8s-1.kafka-k8s-endpoints:9092,kafka-k8s-2.kafka-k8s-endpoints:9092
  password: fm2E0oBidzcnpav1WSNfJXKn0vtgn44G
  tls: disabled
  topic: test-topic
  username: relation-8
ok: "True"
```

````

`````

## Password rotation

Password rotation can be performed in multiple ways, depending on the requirements.

### External clients

There are two ways to rotate credentials of an external client. One is simply to delete and re-create the relation, the other one can be performed without any downtime.

#### With client application downtime

The easiest way to rotate user credentials of client applications is by removing and then re-relating 
the application (either a charm supporting the `kafka-client` interface or a `data-integrator`) with the Apache Kafka charm:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```shell
juju remove-relation kafka <charm-or-data-integrator>

# wait for the relation to be torn down 
juju integrate kafka <charm-or-data-integrator>
```

````

````{tab-item} K8s
:sync: k8s

```shell
juju remove-relation kafka-k8s <charm-or-data-integrator>

# wait for the relation to be torn down
juju integrate kafka-k8s <charm-or-data-integrator>
```

````

`````

The successful credential rotation can be confirmed by retrieving the new password with the action `get-credentials`.

#### Without client application downtime

In some use-cases credentials should be rotated with no or limited application downtime.
If credentials should be rotated with no or limited downtime, you can deploy a new charm with the same permissions and resource definition, for example:

```shell
juju deploy data-integrator rotated-user \
  --config topic-name=test-topic \
  --config extra-user-roles=producer,consumer
```

The `data-integrator` charm can then be integrated with the Apache Kafka charm to create a new user:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```shell
juju integrate kafka rotated-user
```

````

````{tab-item} K8s
:sync: k8s

```shell
juju integrate kafka-k8s rotated-user
```

````

`````

At this point, we effectively have two overlapping users, so that applications can swap the password
from one to another.
If the applications consist of fleets of independent producers and consumers, user credentials can be rotated
progressively across fleets, such that no effective downtime is achieved.

Once all applications have rotated their credentials, it is then safe to remove data first `data-integrator` charm

```shell
juju remove-application data-integrator
```
