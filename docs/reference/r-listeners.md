# Apache Kafka listeners

Charmed Apache Kafka comes with a set of listeners that can be enabled for
inter- and intra-cluster communication. 

*Internal listeners* are used for internal traffic and exchange of information 
between Apache Kafka brokers, whereas *external listeners* are used for external clients
to be optionally enabled based on the relations created on particular
charm endpoints. Each listener is characterized by a specific port, scope and protocol. 

In the following table, we summarize the protocols, the port and
the relation that each listener is bound to. Note that based on whether a `certificates`
relation is present, one of two mutually exclusive types of listeners can be 
opened. 

| Listener name | Driving endpoints                      | Protocol       | Port  | Scope    |
|---------------|----------------------------------------|----------------|-------|----------|
| SASL_INTERNAL | `cluster`                              | SASL_PLAINTEXT | `19092` | internal |
| SASL_INTERNAL | `cluster` + `certificates`             | SASL_SSL       | `19093` | internal |
| SASL_EXTERNAL | `kafka-client`                         | SASL_PLAINTEXT | `9092`  | external |
| SASL_EXTERNAL | `kafka-client` + `certificates`        | SASL_SSL       | `9093`  | external |
| SSL_EXTERNAL  | `trusted-certificate` + `certificates` | SSL            | `9094`  | external |
| SSL_EXTERNAL  | `trusted-ca` + `certificates`          | SSL            | `9094`  | external |

[note]
Since `cluster` is a peer-relation, the `SASL_INTERNAL` listener is always enabled.
[/note]