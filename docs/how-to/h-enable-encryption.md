# How to enable encryption

The Apache Kafka and Apache ZooKeeper charms implement the Requirer side of the [`tls-certificates/v1`](https://github.com/canonical/charm-relation-interfaces/blob/main/interfaces/tls_certificates/v1/README.md) charm relation. Therefore, any charm implementing the Provider side could be used.
To enable encryption, you should first deploy a TLS certificates Provider charm. 

## Deploy a TLS Provider charm

One possible option, suitable for testing, could be to use the `self-signed-certificates` charm.
However, this setup is not recommended for production clusters. 

To deploy a `self-signed-certificates` charm:

```shell
# deploy the TLS charm
juju deploy self-signed-certificates --channel=edge
# add the necessary configurations for TLS
juju config self-signed-certificates ca-common-name="Test CA"
```

Please refer to [this post](https://charmhub.io/topics/security-with-x-509-certificates) for an overview of the TLS certificates Providers charms and some guidance on how to choose the right charm for your use case. 

## Relate the charms

```
juju relate <tls-certificates> zookeeper
juju relate <tls-certificates> kafka:certificates
```

where `<tls-certificates>` is the name of the TLS certificate provider charm deployed.

[note]
If Apache Kafka and Apache ZooKeeper are already related, they will start renegotiating the relation to provide each other certificates and enable/open to correct ports/connections. Otherwise, relate them after the both relations with the `<tls-certificates>`.
[/note]

## Manage keys

Updates to private keys for certificate signing requests (CSR) can be made via the `set-tls-private-key` action.
```shell
# Updates can be done with auto-generated keys with
juju run kafka/<unit_id> set-tls-private-key
```

Passing keys to external/internal keys should *only be done with* `base64 -w0` *not* `cat`, as follows:

```shell
# generate shared internal key
openssl genrsa -out internal-key.pem 3072
# apply keys on each unit
juju run kafka/<unit_id> set-tls-private-key "internal-key=$(base64 -w0 internal-key.pem)"
```

To disable TLS remove the relation:

```shell
juju remove-relation kafka <tls-certificates>
juju remove-relation zookeeper <tls-certificates>
```

where `<tls-certificates>` is the name of the TLS certificate provider charm deployed.