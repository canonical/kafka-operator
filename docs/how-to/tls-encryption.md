---
myst:
  html_meta:
    description: "Enable TLS encryption for Charmed Apache Kafka - secure client and internal communications with certificate management."
---

(how-to-tls-encryption)=
# How to enable TLS encryption

By default, Charmed Apache Kafka uses TLS encryption for all internal communication - inter-broker and broker-controller. This is achieved with self-signed certificates that are generated on each application unit at deploy time.

For external client connections, Charmed Apache Kafka operators implement the requirer side of the [`tls-certificates/v4`](https://github.com/canonical/tls-certificates-interface/blob/main/lib/charms/tls_certificates_interface/v4/tls_certificates.py) charm relation. Therefore, any charm implementing the Provider side could be used.

## Prerequisites

For this guide, you need an active Charmed Apache Kafka application. Follow the
[deployment guide](how-to-deploy-anywhere) to set up the appropriate VM or K8s
environment.

## Enable TLS encryption for client communication

To enable external client encryption, you should first deploy a TLS certificates Provider charm. For this guide, we will be using the `self-signed-certificates` charm.

```{warning}
Using self-signed certificates is not recommended for production systems. Instead follow your organisations best-practices for managing TLS certificates.
Please refer to [this post](https://charmhub.io/topics/security-with-x-509-certificates) for an overview of the TLS certificates Providers charms and some guidance on how to choose the right charm for your use case. 
```

To deploy the `self-signed-certificates` application:

```bash
juju deploy self-signed-certificates --config ca-common-name="Test CA"
```

To enable TLS encryption for client connections with Charmed Apache Kafka, integrate the Charmed Apache Kafka application to the `tls-certificates` provider application via the `certificates` relation interface:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```bash
juju integrate kafka:certificates self-signed-certificates
```

````

````{tab-item} K8s
:sync: k8s

```bash
juju integrate kafka-k8s:certificates self-signed-certificates
```

````

`````

## (Optional) Trust external CAs for mTLS authentication

See the [mTLS client encryption](how-to-create-mtls-client-credentials) guide.
<!-- TODO: add detail here -->

## (Optional) Replace self-signed with provided certificates for internal communication

To replace the auto-generated self-signed certificates used for inter-broker and broker-controller communication, integrate the Charmed Apache Kafka applications to the `tls-certificates` provider application via the `peer-certificates` relation interface:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```bash
juju integrate kafka:peer-certificates <TLS-provider-charm>
```

````

````{tab-item} K8s
:sync: k8s

```bash
juju integrate kafka-k8s:peer-certificates <TLS-provider-charm>
```

````

`````

The old self-signed certificates will be removed, and new certificates will be issued using the certificate authority in the provider application. See [Security with x.509 certificates](https://charmhub.io/topics/security-with-x-509-certificates) topic for more information and guidance on selecting a TLS provider charm.

## (Optional) Use external private keys

By default, Charmed Apache Kafka applications will generate their own internal private key for identifying brokers for client connections. While this is secure for most production deployments, you may wish to specify your own private key to use. [Juju secrets](https://canonical.com/juju/docs/juju-cli/3.6/reference/secret/) can be provided by users to specify external private keys for certificate signing requests (CSRs) and generated certificates.

First, generate (or otherwise obtain) a private keys for each Charmed Apache Kafka unit. For example, if you have three `kafka` units, generate external private keys for each one:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```bash
openssl genrsa -out kafka-0.key 4096
openssl genrsa -out kafka-1.key 4096
openssl genrsa -out kafka-2.key 4096
```

Then, add these external private keys to a new Juju secret:

```bash
juju add-secret external-kafka-pks kafka-0="$(cat kafka-0.key)" kafka-1="$(cat kafka-1.key)" kafka-2="$(cat kafka-2.key)"
```

````

````{tab-item} K8s
:sync: k8s

```bash
openssl genrsa -out kafka-k8s-0.key 4096
openssl genrsa -out kafka-k8s-1.key 4096
openssl genrsa -out kafka-k8s-2.key 4096
```

Then add the keys to a Juju secret:

```bash
juju add-secret external-kafka-pks \
  kafka-k8s-0="$(cat kafka-k8s-0.key)" \
  kafka-k8s-1="$(cat kafka-k8s-1.key)" \
  kafka-k8s-2="$(cat kafka-k8s-2.key)"
```

````

`````

```{note}
The Juju secret keys **MUST** follow the naming constraint of `<kafka-application-name>-<unit-id>`.
```

Grant the Charmed Apache Kafka application access to the new Juju secret:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```bash
juju grant-secret external-kafka-pks kafka
```

````

````{tab-item} K8s
:sync: k8s

```bash
juju grant-secret external-kafka-pks kafka-k8s
```

````

`````

Take note of the `secret-id` in the response.

<details> <summary> Output example</summary>

An example output may look like:

```text
secret:d2k6hv8co3bs4tge0c8g
```

</details>

Finally, update the Charmed Apache Kafka application configuration to notify it of the new secret:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```bash
juju config kafka tls-private-key=secret:d2k6hv8co3bs4tge0c8g
```

````

````{tab-item} K8s
:sync: k8s

```bash
juju config kafka-k8s tls-private-key=secret:d2k6hv8co3bs4tge0c8g
```

````

`````

Charmed Apache Kafka will read the new secret, and re-request new TLS certificates using the externally provided private key created earlier.

## Disable TLS encryption for client communication

To disable TLS encryption, remove the relation with the `tls-certificates` provider application:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```bash
juju remove-relation kafka <tls-certificates>
```

````

````{tab-item} K8s
:sync: k8s

```bash
juju remove-relation kafka-k8s <tls-certificates>
```

````

`````
