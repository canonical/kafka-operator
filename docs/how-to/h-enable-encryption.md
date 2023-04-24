# How to enable encryption

Note: The TLS settings here are for self-signed-certificates which are not recommended for production clusters, the `tls-certificates-operator` charm offers a variety of configurations, read more on the TLS charm [here](https://charmhub.io/tls-certificates-operator)

## Enable TLS

```shell
# deploy the TLS charm
juju deploy tls-certificates-operator --channel=edge
# add the necessary configurations for TLS
juju config tls-certificates-operator generate-self-signed-certificates="true" ca-common-name="Test CA"
# to enable TLS relate the two applications
juju relate tls-certificates-operator zookeeper
juju relate tls-certificates-operator kafka
```

## Manage keys

Updates to private keys for certificate signing requests (CSR) can be made via the `set-tls-private-key` action.
```shell
# Updates can be done with auto-generated keys with
juju run-action kafka/0 set-tls-private-key --wait
juju run-action kafka/1 set-tls-private-key --wait
juju run-action kafka/2 set-tls-private-key --wait
```

Passing keys to external/internal keys should *only be done with* `base64 -w0` *not* `cat`. With three brokers this schema should be followed:
```shell
# generate shared internal key
openssl genrsa -out internal-key.pem 3072
# apply keys on each unit
juju run-action kafka/0 set-tls-private-key "internal-key=$(base64 -w0 internal-key.pem)"  --wait
juju run-action kafka/1 set-tls-private-key "internal-key=$(base64 -w0 internal-key.pem)"  --wait
juju run-action kafka/2 set-tls-private-key "internal-key=$(base64 -w0 internal-key.pem)"  --wait
```

To disable TLS remove the relation
```shell
juju remove-relation kafka tls-certificates-operator
juju remove-relation zookeeper tls-certificates-operator
```