(reference-broker-listeners)=
# Apache Kafka Listeners

Charmed Apache Kafka K8s comes with a set of listeners that can be enabled to allow for
inter- and intracluster communication.

- **Internal listeners** are used for internal traffic and exchange of information between Apache Kafka brokers
- **Client listeners** are used for clients within the Kubernetes cluster,
- **External listeners** are used for clients outside the Kubernetes cluster.

Listeners are optionally enabled based on the relations created on particular
charm endpoints. Each listener is characterised by a specific port, scope, security protocol and authentication mechanism.

In the following table, we summarise the protocols, the port, and
the relation that each listener is bound to. Note that based on whether a `certificates`
relation is present, one of two mutually exclusive types of listeners can be 
opened.

| Security protocol | Authentication mechanism | Driving endpoints                                      | Port    | Scope    | Listener name                         |
|-------------------|--------------------------|--------------------------------------------------------|---------|----------|---------------------------------------|
| SASL_PLAINTEXT    | `SCRAM-SHA-512`            | `cluster`                                              | `19092` | INTERNAL | `INTERNAL_SASL_PLAINTEXT_SCRAM_SHA_512` |
| SASL_SSL          | `SCRAM-SHA-512`            | `cluster` + `certificates`                             | `19093` | INTERNAL | `INTERNAL_SASL_SSL_SCRAM_SHA_512`       |
| SASL_PLAINTEXT    | `SCRAM-SHA-512`            | `kafka-client`                                         | `9092`  | CLIENT   | `CLIENT_SASL_PLAINTEXT_SCRAM_SHA_512`   |
| SASL_SSL          | `SCRAM-SHA-512`            | `kafka-client` + `certificates`                        | `9093`  | CLIENT   | `CLIENT_SASL_SSL_SCRAM_SHA_512`         |
| SSL               | `SSL`                      | (`trusted-certificate`\|`trusted-ca`) + `certificates` | `9094`  | CLIENT   | `CLIENT_SSL_SSL`                        |
| SASL_PLAINTEXT    | `OAUTHBEARER`              | `kafka-client` + `oauth`                               | `9095`  | CLIENT   | `CLIENT_SASL_PLAINTEXT_OAUTHBEARER`     |
| SASL_SSL          | `OAUTHBEARER`              | `kafka-client` + `oauth` + `certificates`              | `9096`  | CLIENT   | `CLIENT_SASL_SSL_OAUTHBEARER`           |
| SASL_PLAINTEXT    | `SCRAM-SHA-512`            | `kafka-client`                                         | `29092` | EXTERNAL | `EXTERNAL_SASL_PLAINTEXT_SCRAM_SHA_512` |
| SASL_SSL          | `SCRAM-SHA-512`            | `kafka-client` + `certificates`                        | `29093` | EXTERNAL | `EXTERNAL_SASL_SSL_SCRAM_SHA_512`       |
| SSL               | `SSL`                      | (`trusted-certificate`\|`trusted-ca`) + `certificates` | `29094` | EXTERNAL | `EXTERNAL_SSL_SSL`                      |
| SASL_PLAINTEXT    | `OAUTHBEARER`              | `kafka-client` + `oauth`                               | `29095` | EXTERNAL | `EXTERNAL_SASL_PLAINTEXT_OAUTHBEARER`   |
| SASL_SSL          | `OAUTHBEARER`              | `kafka-client` + `oauth` + `certificates`              | `29096` | EXTERNAL | `EXTERNAL_SASL_SSL_OAUTHBEARER`         |

```{note}
Since `cluster` is a peer relation, one of the two `INTERNAL_*` listeners is always enabled.
```
