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
|   Broker   |              `certificate-transfer` + `certificates`             |       SSL      |  `9094` |     client    |
|   Broker   | `kafka-client` (with `mtls-cert` relation-data) + `certificates` |       SSL      |  `9094` |     client    |
