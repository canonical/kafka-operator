(tutorial-enable-encryption)=
# 5. Enable encryption

This is a part of the [Charmed Apache Kafka Tutorial](index.md).

[TLS](https://en.wikipedia.org/wiki/Transport_Layer_Security) is used to encrypt data exchanged between two applications; it secures data transmitted over the network. Typically, enabling TLS within a highly available database, and between a highly available database and client/server applications, requires domain-specific knowledge and a high level of expertise. Fortunately, the domain-specific knowledge has been encoded into Charmed Apache Kafka. This means (re-)configuring TLS on Charmed Apache Kafka is readily available and requires minimal effort on your end.

Juju relations are particularly useful for enabling TLS. 
For example, you can relate Charmed Apache Kafka to the 
[Self-signed Certificates Charm](https://charmhub.io/self-signed-certificates)
using the [tls-certificates](https://charmhub.io/integrations/tls-certificates) interface. 
The `tls-certificates` relation centralises TLS certificate management, handling certificate provisioning, requests, and renewal. This approach allows you to use different certificate providers, including self-signed certificates or external services such as Let's Encrypt.

```{note}
In this tutorial, we will distribute [self-signed certificates](https://en.wikipedia.org/wiki/Self-signed_certificate) to all charms (Charmed Apache Kafka and client applications) that are signed using a root self-signed CA that is also trusted by all applications. 
This setup is only for testing and demonstrating purposes and self-signed certificates are not recommended in a production cluster. For more information about which charm may better suit your use-case, please see the [Security with X.509 certificates](https://charmhub.io/topics/security-with-x-509-certificates) page.
```

## Configure TLS

Before enabling TLS on Charmed Apache Kafka we must first deploy the `self-signed-certificates` charm:

```shell
juju deploy self-signed-certificates --config ca-common-name="Tutorial CA"
```

Wait for the charm to settle into an `active`/`idle` state, as shown by the `juju status` command.

<details> <summary> Output example</summary>

```shell
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  3.6.13   unsupported  17:56:56Z

App                       Version  Status   Scale  Charm                     Channel        Rev  Exposed  Message
data-integrator                    blocked      1  data-integrator           latest/stable  180  no       Please relate the data-integrator with the desired product
kafka                     4.0.0    active       3  kafka                     4/edge         245  no       
kraft                     4.0.0    active       3  kafka                     4/edge         245  no       
self-signed-certificates           active       1  self-signed-certificates  1/stable       317  no       

Unit                         Workload  Agent  Machine  Public address  Ports      Message
data-integrator/0*           blocked   idle   6        10.109.154.254             Please relate the data-integrator with the desired product
kafka/0*                     active    idle   0        10.109.154.47   19093/tcp  
kafka/1                      active    idle   1        10.109.154.171  19093/tcp  
kafka/2                      active    idle   2        10.109.154.82   19093/tcp  
kraft/0*                     active    idle   3        10.109.154.49   9098/tcp   
kraft/1                      active    idle   4        10.109.154.148  9098/tcp   
kraft/2                      active    idle   5        10.109.154.50   9098/tcp   
self-signed-certificates/0*  active    idle   8        10.109.154.248             

Machine  State    Address         Inst id        Base          AZ   Message
0        started  10.109.154.47   juju-030538-0  ubuntu@24.04  dev  Running
1        started  10.109.154.171  juju-030538-1  ubuntu@24.04  dev  Running
2        started  10.109.154.82   juju-030538-2  ubuntu@24.04  dev  Running
3        started  10.109.154.49   juju-030538-3  ubuntu@24.04  dev  Running
4        started  10.109.154.148  juju-030538-4  ubuntu@24.04  dev  Running
5        started  10.109.154.50   juju-030538-5  ubuntu@24.04  dev  Running
6        started  10.109.154.254  juju-030538-6  ubuntu@24.04  dev  Running
8        started  10.109.154.248  juju-030538-8  ubuntu@24.04  dev  Running
```

</details>

To enable TLS on Charmed Apache Kafka, integrate with `self-signed-certificates` charm:

```shell
juju integrate kafka:certificates self-signed-certificates
```

After the charms settle into `active`/`idle` states, the Apache Kafka listeners
should now have been swapped to the default encrypted port `9093`.
This can be tested by testing whether the ports are open/closed with `telnet`:

```shell
telnet <Public IP address> 9092 
telnet <Public IP address> 9093
```

where `Public IP address` is the IP of any Charmed Apache Kafka application units.

Both commands will be **unable to connect** now, as our Apache Kafka cluster
has no active listeners fue to absence of integrated applications.

```{caution}
When no other application is integrated to Charmed Apache Kafka,
the cluster is secured-by-default and external listeners (bound to port `9092`) are disabled,
thus preventing any external incoming connection. 
```

Let's integrate the `data-integrator` application to the Apache Kafka cluster:

```shell
juju integrate data-integrator kafka
```

After all units are back to `active`/`idle`, you will see the new ports in the `juju status` output.
Now try connecting with `telnet` again:

```shell
telnet <Public IP address> 9092 
telnet <Public IP address> 9093
```

The `9092` port connection now should show a connection error,
while the `9093` port should establish a connection.

## Enable TLS encrypted connection

Once TLS is configured on the cluster side, client applications should be configured as well
to connect to the correct port and trust the self-signed CA provided by
the `self-signed-certificates` charm.

Let's deploy our [Apache Kafka Test App](https://charmhub.io/kafka-test-app) again:

```shell
juju deploy kafka-test-app --channel edge
```

Then, enable encryption on the `kafka-test-app` by integrating with
the `self-signed-certificates` charm:

```shell
juju integrate kafka-test-app self-signed-certificates
```

We can then set up the `kafka-test-app` to produce messages with the usual configuration
(note that that the process here is the same as with the unencrypted workflow):

```shell
juju config kafka-test-app topic_name=HOT-TOPIC role=producer num_messages=20
```

Finally, relate with the `kafka` cluster:

```shell
juju integrate kafka kafka-test-app
```

Wait for `active`/`idle` status in `juju status` and check that the messages are pushed into
the Charmed Apache Kafka cluster by inspecting the logs:

```shell
juju exec --application kafka-test-app "tail /tmp/*.log"
```

Refer to the latest logs produced and also check that in the logs the connection
is indeed established with the encrypted port `9093`.

## Remove external TLS certificate

To remove the external TLS and return to the locally generated one,
remove relation with certificates provider:

```shell
juju remove-relation kafka self-signed-certificates
```

The Charmed Apache Kafka application is not using TLS anymore for client connections.

## Clean up

Before proceeding further, let's remove the `kafka-test-app` application:

```shell
juju remove-relation kafka-test-app kafka
juju remove-relation kafka-test-app self-signed-certificates
juju remove-application kafka-test-app --destroy-storage
```
