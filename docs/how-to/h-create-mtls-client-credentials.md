# Create mTLS client credentials

Requirements:

- Charmed Apache Kafka cluster up and running
- [Admin credentials](./h-manage-app.md)
- [Encryption enabled](./h-enable-encryption.md)
- [Java JRE](https://ubuntu.com/tutorials/install-jre#1-overview) installed
- [`charmed-kafka` snap](https://snapcraft.io/charmed-kafka) installed
- [jq](https://snapcraft.io/jq) installed

This guide includes step-by-step instructions on how to create mTLS credentials for a client application to be able to connect to a Charmed Apache Kafka cluster.

## Authentication

```bash
# ---------- Environment
SNAP_KAFKA_PATH=/var/snap/charmed-kafka/current/etc/kafka

# Apache Kafka ports
KAFKA_SASL_PORT=9093
KAFKA_MTLS_PORT=9094

# Apache Kafka servers
KAFKA_SERVERS_SASL=<broker-ip>$KAFKA_SASL_PORT
KAFKA_SERVERS_MTLS=<broker-ip>$KAFKA_MTLS_PORT

# Java keystore and trustore
KAFKA_CLIENT_KEYSTORE_PASSWORD=changeme
KAFKA_CLIENT_TRUSTSTORE_PASSWORD=changeme

# Client information
KAFKA_CLIENT_MTLS_CN=<client-cn>
KAFKA_CLIENT_MTLS_NAME=<client-name>
KAFKA_CLIENT_MTLS_IP=<client-ip>
```

### Retrieve root CA

If you are using the [`tls-certificates-operator` charm](https://charmhub.io/tls-certificates-operator), retrieve the root CA executing the following commands:

```bash
# ---------- Root CA
# Get the root CA to be used by the client
juju show-unit tls-certificates-operator/0 --format json | jq -r '.[]."relation-info"[]."application-data"."self_signed_ca_certificate" // empty' > ss_ca.pem

# Get the root CA private key and password to be used by the client
juju show-unit tls-certificates-operator/0 --format json | jq -r '.[]."relation-info"[]."application-data"."self_signed_ca_private_key" // empty' > ss_ca.key
SS_KEY_PASSWORD=$(juju show-unit tls-certificates-operator/0 --format json | jq -r '.[]."relation-info"[]."application-data"."self_signed_ca_private_key_password" // empty')
```

Otherwise, retrieve root CA from your certificates provider.

### Retrieve server CA

```bash
# ---------- Server CA
# getting the CA used by the server
juju show-unit kafka/0 --format json | jq -r '.[]."relation-info"[]."local-unit".data.ca // empty' > kafka_ca.pem
```

### Create keystore (client cert)

Create a client cert signed by the server

```bash
# ---------- Keystore
# create new private key --> client_key.pem
openssl genrsa -out client_key.pem 4096

# create new csr --> client_csr.pem
openssl req -new -key client_key.pem -out client_csr.pem -subj "/C=US/ST=Denial/L=Springfield/O=Dis/CN=$KAFKA_CLIENT_MTLS_CN"

# sign new csr using new client CA --> client_cert.pem
openssl x509 -req -CA ss_ca.pem -CAkey ss_ca.key -in client_csr.pem -out client_cert.pem -days 365 -CAcreateserial -passin pass:$SS_KEY_PASSWORD

# create new chain --> client_chain.pem
cat ss_ca.pem client_cert.pem client_key.pem > client_chain.pem

# create p12 keystore from chain --> client.keystore.p12
openssl pkcs12 -export -in client_chain.pem \
-out client.keystore.p12 -password pass:$KAFKA_CLIENT_KEYSTORE_PASSWORD \
-name client-chain -noiter -nomaciter
```

### Create trustsore (server cert)

Inject root CA and server CA into the truststore file:

```bash

# ---------- Truststore
charmed-kafka.keytool -keystore client.truststore.jks -storepass $KAFKA_CLIENT_TRUSTSTORE_PASSWORD -noprompt \
  -importcert -alias kafka-ca -file kafka_ca.pem
charmed-kafka.keytool -keystore client.truststore.jks -storepass $KAFKA_CLIENT_TRUSTSTORE_PASSWORD -noprompt \
  -importcert -alias CARoot -file ss_ca.pem
```

### Check certificates validity

```bash

# ---------- Check certs validity
echo "Client certs in Keystore:"
charmed-kafka.keytool -list -keystore client.keystore.p12 -storepass $KAFKA_CLIENT_KEYSTORE_PASSWORD -rfc | grep "Alias name"
charmed-kafka.keytool -list -keystore client.keystore.p12 -storepass $KAFKA_CLIENT_KEYSTORE_PASSWORD -v | grep until

echo "Server certs in Truststore:"
charmed-kafka.keytool -list -keystore client.truststore.jks -storepass $KAFKA_CLIENT_TRUSTSTORE_PASSWORD -rfc | grep "Alias name"
charmed-kafka.keytool -list -keystore client.truststore.jks -storepass $KAFKA_CLIENT_TRUSTSTORE_PASSWORD -v | grep until
```
### mTLS

This is a mutual TLS communication which means:

1. The client needs to trust the server certificates.

2. Instead of usernames and passwords, the client needs its own certificate signed by a certificate trusted by the server for the authentication.

```bash
# Map the CN on the cert to be considered the principal (username)
juju config kafka ssl_principal_mapping_rules='RULE:^.*[Cc][Nn]=([a-zA-Z0-9\.-]*).*$/$1/L,DEFAULT'
```

```bash
# ---------- Create mTLS User credentials
juju ssh kafka/leader "
sudo charmed-kafka.configs \
--bootstrap-server $KAFKA_SERVERS_SASL \
--command-config $SNAP_KAFKA_PATH/client.properties \
--alter --entity-type=users \
--entity-name=$KAFKA_CLIENT_MTLS_CN \
"

```

Create a file called `client-mtls.properties` that should look like:

```bash
security.protocol=SSL
bootstrap.servers=$KAFKA_SERVERS_MTLS
ssl.truststore.location=$SNAP_KAFKA_PATH/client.truststore.jks
ssl.truststore.password=$KAFKA_CLIENT_TRUSTSTORE_PASSWORD
ssl.truststore.type=JKS
ssl.keystore.location=$SNAP_KAFKA_PATH/client.keystore.p12
ssl.keystore.password=$KAFKA_CLIENT_KEYSTORE_PASSWORD
ssl.keystore.type=PKCS12
ssl.client.auth=required
```

## Authorisation

### Manage authorisation through ACLs

Grant read and write privileges to user over _group_, _topic_ and _transaction_ resources:

```bash
juju ssh kafka/leader "
echo 'LOG: Creating ACLs for SASL user'

sudo charmed-kafka.acls --bootstrap-server $KAFKA_SERVERS_SASL --command-config $SNAP_KAFKA_PATH/client.properties \
--add --allow-principal User:$KAFKA_CLIENT_MTLS_CN \
--operation READ --operation DESCRIBE --group='*'
sudo charmed-kafka.acls --bootstrap-server $KAFKA_SERVERS_SASL --command-config $SNAP_KAFKA_PATH/client.properties \
--add --allow-principal User:$KAFKA_CLIENT_MTLS_CN \
--operation READ --operation DESCRIBE --operation CREATE --operation WRITE --operation DELETE --operation ALTER --operation ALTERCONFIGS --topic='*'

sudo charmed-kafka.acls --bootstrap-server $KAFKA_SERVERS_SASL --command-config $SNAP_KAFKA_PATH/client.properties \
--add --allow-principal User:$KAFKA_CLIENT_MTLS_CN \
--operation DESCRIBE --operation WRITE --transactional-id '*'
"
```

## Test access

```bash
# ---------- Test Access
# Copy the files to a path readable by the `charmed-kafka` snap commands
sudo cp client.truststore.jks $SNAP_KAFKA_PATH/
sudo cp client.keystore.p12 $SNAP_KAFKA_PATH/
sudo cp client-mtls.properties $SNAP_KAFKA_PATH/

# Apply file permissions to be readable by the snap
sudo chown snap_daemon:root $SNAP_KAFKA_PATH/client-mtls.properties
sudo chown snap_daemon:root $SNAP_KAFKA_PATH/client.keystore.p12
sudo chown snap_daemon:root $SNAP_KAFKA_PATH/client.truststore.jks

# Use newly created credentials to create a topic and list existing topics
sudo charmed-kafka.topics --bootstrap-server $KAFKA_SERVERS_MTLS --command-config $SNAP_KAFKA_PATH/client-mtls.properties \
--create --topic EXAMPLE-TOPIC

sudo charmed-kafka.topics --list --bootstrap-server $KAFKA_SERVERS_MTLS --command-config $SNAP_KAFKA_PATH/client-mtls.properties
```