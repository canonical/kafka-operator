---
myst:
  html_meta:
    description: "Charmed Apache Kafka listeners reference - internal and client listener protocols, ports, and endpoint configurations."
---

(reference-broker-listeners)=
# Apache Kafka listeners

Charmed Apache Kafka comes with a set of listeners that can be enabled for
inter-broker and broker-controller communication, and for client communication. 

*Internal listeners* are used for internal traffic and exchange of information 
between Apache Kafka brokers and controllers. These will be created by default.

*Client listeners* are used for external clients, and are optionally enabled
based on the relations created on particular charm endpoints.
Each listener is characterised by a specific port, scope and protocol. 

In the following table, we summarise the protocols, the port and
the relation that each listener is bound to. Note that based on whether a `certificates`
relation is present, one of two mutually exclusive types of listeners can be 
opened. 

|    Usage   |                         Driving endpoints                        |    Protocol    |  Port   |     Scope     |
|:----------:|:-----------------------------------------------------------------|:--------------:|:-------:|:-------------:|
|   Broker   |               `cluster` (+ optional `peer-certificates`)         |    SASL_SSL    | `19093` | internal-only |
| Controller |               `cluster` (+ optional `peer-certificates`)         |    SASL_SSL    |  `9098` | internal-only |
|            |                                                                  |                |         |               |
|   Broker   |                          `kafka-client`                          | SASL_PLAINTEXT |  `9092` |     client    |
|   Broker   |                  `kafka-client` + `certificates`                 |    SASL_SSL    |  `9093` |     client    |
|   Broker   |                    `client-cas` + `certificates`                 |       SSL      |  `9094` |     client    |
|   Broker   | `kafka-client` (with `mtls-cert` relation-data) + `certificates` |       SSL      |  `9094` |     client    |
|   Broker   |                          `oauth`                                 | SASL_PLAINTEXT |  `9095` |     client    |
|   Broker   |                    `oauth` + `certificates`                      |    SASL_SSL    |  `9096` |     client    |

Internal (broker-controller and inter-broker) communications always use `SASL_SSL`.
When no `peer-certificates` relation is present, the charm uses auto-generated
self-signed certificates instead of certificates provided by a
TLS Certificate Provider charm.

```{note}
Additional listeners can be defined using the `extra-listeners` configuration option,
which allocates a distinct port for each authentication scheme starting from a configurable
base port (offset by 20001-50000).
See the configurations reference for [VM](https://charmhub.io/kafka/configure?channel=4/stable#extra-listeners)
or [K8s](https://charmhub.io/kafka-k8s/configure?channel=4/stable#extra-listeners)
for details.
```

## External listeners on Kubernetes

```{note}
This section applies to the K8s charm only.
```

When `expose-external=nodeport`, the charm creates NodePort services that expose
the client listeners outside the Kubernetes cluster:

| Usage | Protocol | External listener port | Scope |
|---|---|---:|---|
| Broker | SASL_PLAINTEXT (SCRAM-SHA-512) | `29092` | external |
| Broker | SASL_SSL (SCRAM-SHA-512) | `29093` | external |
| Broker | SSL (mTLS) | `29094` | external |
| Broker | SASL_PLAINTEXT (OAuth) | `29095` | external |
| Broker | SASL_SSL (OAuth) | `29096` | external |

Kubernetes assigns the corresponding NodePorts. See [External K8s
connection](how-to-external-k8s-connection) for setup and discovery instructions.
