This is part of the [Charmed Kafka Tutorial](/t/charmed-kafka-tutorial-overview/10571). Please refer to this page for more information and the overview of the content. 

## Transport Layer Security (TLS)

[TLS](https://en.wikipedia.org/wiki/Transport_Layer_Security) is used to encrypt data exchanged between two applications; it secures data transmitted over the network. Typically, enabling TLS within a highly available database, and between a highly available database and client/server applications, requires domain-specific knowledge and a high level of expertise. Fortunately, the domain-specific knowledge has been encoded into Charmed Kafka. This means (re-)configuring TLS on Charmed Kafka is readily available and requires minimal effort on your end.

Again, relations come in handy here as TLS is enabled via relations; i.e. by relating Charmed Kafka to the [Self-signed Certificates Charm](https://charmhub.io/self-signed-certificates) via the [`tls-certificates`](https://github.com/canonical/charm-relation-interfaces/blob/main/interfaces/tls_certificates/v1/README.md) charm relations. The `tls-certificates` relation centralises TLS certificate management in a consistent manner and handles providing, requesting, and renewing TLS certificates, making it possible to use different providers, like the self-signed certificates but also other services, e.g. Let's Encrypt. 

> *Note: In this tutorial, we will distribute [self-signed certificates](https://en.wikipedia.org/wiki/Self-signed_certificate) to all charms (Kafka, Zookeeper and client applications) that are signed using a root self-signed CA
that is also trusted by all applications. This setup is only for show-casing purposes and self-signed certificates should **never** be used in a production cluster. For more information about which charm may better suit your use-case, please refer to [this post](https://charmhub.io/topics/security-with-x-509-certificates).* 

### Configure TLS
Before enabling TLS on Charmed Kafka we must first deploy the `self-signed-certificates` charm:
```shell
juju deploy self-signed-certificates --config ca-common-name="Tutorial CA"
```

Wait for the charm settles into an `active/idle` state, as shown by the `juju status`

```shell
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  3.1.6    unsupported  10:20:59Z

App                        Version  Status  Scale  Charm                      Channel    Rev  Exposed  Message
...
self-signed-certificates            active      1  self-signed-certificates   stable     72   no       
...

Unit                          Workload  Agent  Address    Ports  Message
...
self-signed-certificates/0*   active    idle   10.1.36.91        
...
```

To enable TLS on Charmed Kafka, relate the both the `kafka` and `zookeeper` charms with the
`self-signed-certificates` charm:
```shell
juju relate zookeeper self-signed-certificates
juju relate kafka:certificates self-signed-certificates
```

After the charms settle into `active/idle` states, the Kafka listeners should now have been swapped to the 
default encrypted port 9093. This can be tested by testing whether the ports are open/closed with `telnet`

```shell
telnet <IP> 9092 
telnet <IP> 9093
```

### Enable TLS encrypted connection

Once the Kafka cluster is enabled to use encrypted connection, client applications should be configured as well to connect to
the correct port as well as trust the self-signed CA provided by the `self-signed-certificates` charm. 

Make sure that the `kafka-test-app` is not connected to the Kafka charm, by removing the relation if it exists

```shell
juju remove-relation kafka-test-app kafka
```

Then enable encryption on the `kafka-test-app` by relating with the ` self-signed-certificates` charm

```shell
juju relate kafka-test-app self-signed-certificates
```

We can then set up the `kafka-test-app` to produce messages with the usual configuration (note that there is no difference 
here with the unencrypted workflow)

```shell
juju config kafka-test-app topic_name=test_encryption_topic role=producer num_messages=25
```

and then relate with the `kafka` cluster

```shell
juju relate kafka kafka-test-app
```

As before, you can check that the messages are pushed into the Kafka cluster by inspecting the logs

```shell
juju exec --application kafka-test-app "tail /tmp/*.log"
```

Note that if the `kafka-test-app` was running before, there may be multiple logs related to the different
runs. Refer to the latest logs produced and also check that in the logs the connection is indeed established 
with the encrypted port 9093. 

### Remove external TLS certificate
To remove the external TLS and return to the locally generate one, un-relate applications:
```shell
juju remove-relation kafka self-signed-certificates
juju remove-relation zookeeper self-signed-certificates
```

The Charmed Kafka application is not using TLS anymore.