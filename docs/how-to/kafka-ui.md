(how-to-kafka-ui)=
# How to facilitate administrative tasks using Kafbat's Kafka UI

Although administration of a Charmed Apache Kafka cluster is possible using the command line interface (CLI) and various utilities shipped with the Apache Kafka snap, some administrators prefer a graphical user interface (GUI) which facilitates monitoring of the Apache Kafka cluster and performing various administrative tasks. Therefore, charmed Apache Kafka solution includes a charmed operator for [Kafbat's Kafka UI](https://github.com/kafbat/kafka-ui), which enables users to:

- View Apache Kafka cluster configuration, topics, ACLs, consumer groups and more
- Broker performance monitoring via JMX metrics dashboards
- Seamless integration with other Charmed Apache Kafka operators, like [Charmed Apache Kafka Connect](https://charmhub.io/kafka-connect) and [Charmed Karapace](https://charmhub.io/karapace)

In this guide, you will deploy the Charmed Kafka UI operator, integrate it with the Charmed Apache Kafka and other related products, and enable authentication and TLS for securing access to the Kafka UI.

## Prerequisites

It is assumed that you have a running Apache Kafka cluster using the Charmed Apache Kafka operator. If you are unsure on how to achieve that, it is recommended to review the [Deploy Apache Kafka](tutorial-deploy) tutorial first. The output of the `juju status` command for a cluster running 3 brokers and 3 KRaft controllers will be:

```text
Model  Controller  Cloud/Region         Version  SLA          Timestamp
ui     lxd         localhost/localhost  3.6.9    unsupported  08:37:59+01:00

App         Version  Status  Scale  Charm  Channel  Rev  Exposed  Message
controller  4.0.0    active      3  kafka  4/edge   239  no
kafka       4.0.0    active      3  kafka  4/edge   239  no

Unit           Workload  Agent  Machine  Public address  Ports      Message
controller/0   active    idle   3        10.160.219.43   9098/tcp
controller/1*  active    idle   4        10.160.219.30   9098/tcp
controller/2   active    idle   5        10.160.219.64   9098/tcp
kafka/0        active    idle   0        10.160.219.42   19093/tcp
kafka/1        active    idle   1        10.160.219.90   19093/tcp
kafka/2*       active    idle   2        10.160.219.114  19093/tcp

Machine  State    Address         Inst id        Base          AZ  Message
0        started  10.160.219.42   juju-a00eba-0  ubuntu@24.04      Running
1        started  10.160.219.90   juju-a00eba-1  ubuntu@24.04      Running
2        started  10.160.219.114  juju-a00eba-2  ubuntu@24.04      Running
3        started  10.160.219.43   juju-a00eba-3  ubuntu@24.04      Running
4        started  10.160.219.30   juju-a00eba-4  ubuntu@24.04      Running
5        started  10.160.219.64   juju-a00eba-5  ubuntu@24.04      Running
```

## Deploy charmed Kafka UI

To deploy the charmed Kafka UI operator, simply use the following command:

```bash
juju deploy kafka-ui --channel latest/edge
```

Once the charmed Kafka UI operator is deployed, it will end up in `blocked` state, since it needs to be integrated with a charmed Apache Kafka cluster. The output of `juju status` command will be like below:

```text
...
kafka-ui/0*    blocked   idle   6        10.160.219.25              application needs Kafka client relation
...
```

## Integrate charmed Kafka UI with Apache Kafka

To activate the charmed Kafka UI application, integrate it with the charmed Apache Kafka application:

```bash
juju integrate kafka-ui kafka
```

After a few minutes, the charmed Kafka UI application should be in `active|idle` state.

## Configure authentication

Authentication is enabled by default on the charmed Kafka UI application for the internal `admin` user. To change the `admin` user's password, you need to define a Juju secret with your desired credentials and configure the charmed Kafka UI application to use that secret. The process is as follows:

First, add a custom secret for the internal admin user with your desired password:

```bash
juju add-secret ui-secret admin='My$trongP4ss'
```

You will receive a secret ID in response, for example:

```text
secret:d4aph58sv8l31ign9590
```

Then, grant access to the secret with:

```bash
juju grant-secret ui-secret kafka-ui
```

Finally, configure the UI application to use the provided secret:

```bash
juju config kafka-ui system-users=secret:d4aph58sv8l31ign9590
```

## Access the Kafka UI

To access the UI, simply open a web browser and point it to the `https://{KAFKA_UI_IP}:8080`. `KAFKA_UI_IP` is the IP address of the Kafka UI application, which you can either copy from the output of the `juju status` command, or retrieve it using the following command:

```bash
KAFKA_UI_IP=$(juju status --format json | jq -r '.applications."kafka-ui".units.[]."public-address"')
```

```{note}
By default, charmed Kafka UI uses a self-signed certificate to secure communications. You need to instruct your web browser to trust this certificate. More details on how to do that for Firefox and Google Chrome browsers can be found below:

- **Firefox** - [Set up Certificate Authorities (CAs) in Firefox](https://support.mozilla.org/en-US/kb/setting-certificate-authorities-firefox)
- **Google Chrome** - [Set up TLS (or SSL) inspection on Chrome devices](https://support.google.com/chrome/a/answer/3505249?hl=en)
```


You should see an authentication page like below, in which you can use the `admin` username and the password configured before to log in.

```
todo: add pic
```

Once logged in, you can use the left menu to access the brokers, KRaft controllers, topics, schemas, and connectors configuration along with various monitoring metrics. To familiarise yourself with Kafbat's Kafka UI features, it is advised to consult the product's [official documentation](https://ui.docs.kafbat.io/).

## Integrate charmed Kafka UI with other products

The charmed Kafka UI operator can integrate with other charmed operators, including the charmed Kafka Connect and the charmed Karapace operators. For more information on these products and their use-cases, please refer to the [How to use Kafka Connect for ETL workloads](how-to-use-kafka-connect-for-etl-workloads) and [Schemas and serialisation](how-to-schemas-serialisation) guides.

If you have followed aforementioned guides, you can integrate the charmed Kafka Connect and charmed Karapace applications with the Kafka UI using:

```bash
juju integrate kafka-ui kafka-connect
juju integrate kafka-ui karapace
```

Once all applications settle to `active|idle` state, you will have access to the Kafka Connect and Karapace configuration and current state via the `Kafka Connect` and `Schema Registry` menus in the Kafka UI web interface respectively. 

## Manage TLS certificates

While charmed Kafka UI uses a self-signed certificate to secure communications, this set-up is not recommended for production environments. To secure communications with the Kafka UI, it is advised to use a TLS certificate signed by a trusted certificate authority (CA).

Charmed Kafka UI operator, like the Apache Kafka charm itself, implements the **requirer** side of the [`tls-certificates/v4`](https://github.com/canonical/tls-certificates-interface/blob/main/lib/charms/tls_certificates_interface/v4/tls_certificates.py) charm relation. Therefore, any charm implementing the **provider** side could be used to provide signed certificates.

For more information and guidance on selecting a TLS provider charm, see [Security with x.509 certificates](https://charmhub.io/topics/security-with-x-509-certificates) topic. Once you have your TLS provider ready with the signed certificates, you can simply integrate it with the Kafka UI application using:

```bash
juju integrate kafka-ui <trusted-tls-provider-app>
```

The old self-signed certificate will be removed, and the new certificate issued by the certificate authority in the provider application will be used. After the UI application reports `active|idle` state, you can use `HTTPS` to securely access the Kafka UI, using the `https://{KAFKA_UI_IP}:8080` URL, and verify that the certificate has changed.
