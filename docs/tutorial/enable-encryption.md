(tutorial-enable-encryption)=
# 6. Enable encryption

This is a part of the [Charmed Apache Kafka Tutorial](index.md).

## Transport Layer Security (TLS)

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

### Configure TLS

Before enabling TLS on Charmed Apache Kafka we must first deploy the `self-signed-certificates` charm:

```shell
juju deploy self-signed-certificates --config ca-common-name="Tutorial CA"
```

Wait for the charm to settle into an `active/idle` state, as shown by the `juju status`.

<details> <summary> Output example</summary>

```shell
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  3.6.12   unsupported  00:25:23Z

App                       Version  Status   Scale  Charm                     Channel        Rev  Exposed  Message
data-integrator                    blocked      1  data-integrator           latest/stable  180  no       Please relate the data-integrator with the desired product
kafka                     4.0.0    active       3  kafka                     4/edge         245  no       
kafka-test-app                     active       1  kafka-test-app            latest/edge     15  no       Topic TOP-PICK enabled with process consumer
kraft                     4.0.0    active       3  kafka                     4/edge         245  no       
self-signed-certificates           active       1  self-signed-certificates  1/stable       317  no       

Unit                         Workload  Agent  Machine  Public address  Ports           Message
data-integrator/0*           blocked   idle   6        10.168.161.107                  Please relate the data-integrator with the desired product
kafka-test-app/0*            active    idle   7        10.168.161.157                  Topic TOP-PICK enabled with process consumer
kafka/0                      active    idle   0        10.168.161.221  9092,19093/tcp  
kafka/1*                     active    idle   1        10.168.161.6    9092,19093/tcp  
kafka/2                      active    idle   2        10.168.161.12   9092,19093/tcp  
kraft/0                      active    idle   3        10.168.161.5    9098/tcp        
kraft/1                      active    idle   4        10.168.161.212  9098/tcp        
kraft/2*                     active    idle   5        10.168.161.33   9098/tcp        
self-signed-certificates/0*  active    idle   8        10.168.161.210                  

Machine  State    Address         Inst id         Base          AZ   Message
0        started  10.168.161.221  juju-67d727-0   ubuntu@24.04  dev  Running
1        started  10.168.161.6    juju-67d727-1   ubuntu@24.04  dev  Running
2        started  10.168.161.12   juju-67d727-2   ubuntu@24.04  dev  Running
3        started  10.168.161.5    juju-67d727-3   ubuntu@24.04  dev  Running
4        started  10.168.161.212  juju-67d727-4   ubuntu@24.04  dev  Running
5        started  10.168.161.33   juju-67d727-5   ubuntu@24.04  dev  Running
6        started  10.168.161.107  juju-67d727-6   ubuntu@24.04  dev  Running
7        started  10.168.161.157  juju-67d727-7   ubuntu@22.04  dev  Running
8        started  10.168.161.210  juju-67d727-8   ubuntu@24.04  dev  Running
```

</details>

To enable TLS on Charmed Apache Kafka, integrate with `self-signed-certificates` charm:

```shell
juju integrate kafka:certificates self-signed-certificates
```

After the charms settle into `active/idle` states, the Apache Kafka listeners should now have been swapped to the
default encrypted port `9093`. This can be tested by testing whether the ports are open/closed with `telnet`:

```shell
telnet <Public IP address> 9092 
telnet <Public IP address> 9093
```

where `Public IP address` is the IP of any Charmed Apache Kafka application units.

The `9092` port connection now should show a connection error,
while `9093` port should establish connection.

### Enable TLS encrypted connection

Once TLS is configured on the cluster side, client applications should be configured as well to connect to
the correct port and trust the self-signed CA provided by the `self-signed-certificates` charm.

Make sure that the `kafka-test-app` is not connected to the Charmed Apache Kafka, by removing the relation if it exists:

```shell
juju remove-relation kafka-test-app kafka
```

Then, enable encryption on the `kafka-test-app` by relating with the `self-signed-certificates` charm:

```shell
juju integrate kafka-test-app self-signed-certificates
```

We can then set up the `kafka-test-app` to produce messages with the usual configuration (note that there is no difference 
here with the unencrypted workflow):

```shell
juju config kafka-test-app topic_name=HOT-TOPIC role=producer num_messages=25
```

Then relate with the `kafka` cluster:

```shell
juju integrate kafka kafka-test-app
```

As before, you can check that the messages are pushed into the Charmed Apache Kafka cluster by inspecting the logs:

```shell
juju exec --application kafka-test-app "tail /tmp/*.log"
```

Note that if the `kafka-test-app` was running before, there may be multiple logs related to the different
runs. Refer to the latest logs produced and also check that in the logs the connection is indeed established
with the encrypted port `9093`.

### Remove external TLS certificate

To remove the external TLS and return to the locally generated one, remove relation with certificates provider:

```shell
juju remove-relation kafka self-signed-certificates
```

The Charmed Apache Kafka application is not using TLS anymore for client connections.
