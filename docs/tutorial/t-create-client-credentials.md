# Create Client Credentials

After having succesfully deployed a Kafka cluster you most probably would like to have client applications to connect to this cluster.

## Install required software

### Keytool (Java)

If your clients applications are based on Java, consider that it might need to use special Java file formats for the certificates called keystore and trustore.

To generate these files we will need `keytool` binary. This commes preinstalled with any Java installation.

Make sure you have Java installed and keytool was installed with it.

```bash
$ java --version
openjdk 11.0.19 2023-04-18
OpenJDK Runtime Environment (build 11.0.19+7-post-Ubuntu-0ubuntu120.04.1)
OpenJDK 64-Bit Server VM (build 11.0.19+7-post-Ubuntu-0ubuntu120.04.1, mixed mode, sharing)

$ keytool -h
Key and Certificate Management Tool

Commands:

 -certreq            Generates a certificate request
 -changealias        Changes an entry's alias
 -delete             Deletes an entry
 -exportcert         Exports certificate
 -genkeypair         Generates a key pair
 -genseckey          Generates a secret key
 -gencert            Generates certificate from a certificate request
 -importcert         Imports a certificate or a certificate chain
 -importpass         Imports a password
 -importkeystore     Imports one or all entries from another keystore
 -keypasswd          Changes the key password of an entry
 -list               Lists entries in a keystore
 -printcert          Prints the content of a certificate
 -printcertreq       Prints the content of a certificate request
 -printcrl           Prints the content of a CRL file
 -storepasswd        Changes the store password of a keystore

Use "keytool -?, -h, or --help" for this help message
Use "keytool -command_name --help" for usage of command_name.
Use the -conf <url> option to specify a pre-configured options file.
```

### Kafka CLI Client

To verify the credentials we will generate are properly working we will be installing a Kafka CLI client.

```bash
$ sudo snap install --edge charmed-kafka

# Verify the snap has been installed
$ snap info charmed-kafka
name:      charmed-kafka
summary:   Charmed Kafka for Charmed Operators
publisher: Canonical Data Platform (dataplatformbot)
store-url: https://snapcraft.io/charmed-kafka
contact:   https://chat.charmhub.io/charmhub/channels/data-platform
license:   unset
description: |
  This is a snap that bundles Kafka together with other tools of its
  ecosystem in order to be used in Charmed Operators, providing automated
  operations management from day 0 to day 2 on the Apache Kafka event
  streaming platform deployed on top of a Virtual Machine cluster and K8s
  cluster. It is an open source, end-to-end, production ready data platform
  on top of cloud native technologies.

  This bundle together with its charm comes with features such as:

  * Fault-tolerance, replication, scalability and high-availability
  out-of-the-box.
  * SASL/SCRAM auth for Broker-Broker and Client-Broker authenticaion enabled
  by default.
  * Access control management supported with user-provided ACL lists.
commands:
  - charmed-kafka.acls
  - charmed-kafka.cluster
  - charmed-kafka.configs
  - charmed-kafka.console-consumer
  - charmed-kafka.console-producer
  - charmed-kafka.consumer-groups
  - charmed-kafka.consumer-perf-test
  - charmed-kafka.dump-log
  - charmed-kafka.get-offsets
  - charmed-kafka.kafka-streams-application-reset
  - charmed-kafka.leader-election
  - charmed-kafka.log-dirs
  - charmed-kafka.producer-perf-test
  - charmed-kafka.reassign-partitions
  - charmed-kafka.replica-verification
  - charmed-kafka.run-class
  - charmed-kafka.storage
  - charmed-kafka.topics
  - charmed-kafka.transactions
  - charmed-kafka.trogdor
  - charmed-kafka.verifiable-consumer
  - charmed-kafka.verifiable-producer
  - charmed-kafka.zookeeper-shell
services:
  charmed-kafka.daemon: simple, disabled, inactive
snap-id:      PEGF4Of4BpcyjkBco8QMTwQo0kkrv8c3
tracking:     3/edge
refresh-date: 9 days ago, at 13:47 -05
channels:
  3/stable:    –
  3/candidate: –
  3/beta:      –
  3/edge:      3.3.2 2023-03-28 (16) 167MB -
installed:     3.3.2            (16) 167MB -
```

> At the moment of writing this tutorial the charmed-kafka snap is not yet available on the stable channel. Thus, we will be using the edge channel.

Snaps have constrained access to files as they are designed focused on security. So, once we have created a set of client credentials we will be copying those files into a folder path that the snap has access to read and write, else you might get a permission denied error.

```bash
SNAP_KAFKA_PATH=/var/snap/charmed-kafka/current/etc/kafka
```

### jq

This is a utility to parse JSON objects from the CLI.

```bash
sudo snap install jq
```

> It just makes the tutorial easier

## Authentication

There are two protocols options for the client authentication

- Option A: SASL_SSL (Server cert + User and pass)
- Option B: mTLS (Server cert + Client cert signed by server)

### Applicable for both authentication options

Define the following variables in advance:

```bash
# ---------- Environment
# Certs
CERT_EXPIRATION_DAYS=7300 # 20 years expiration example

# Kafka servers
KAFKA_SERVERS_SASL=172.20.10.4:9093,172.20.10.5:9093,172.20.10.6:9093 # CHANGE_ME
KAFKA_SERVERS_MTLS=172.20.10.4:9094,172.20.10.5:9094,172.20.10.6:9094 # CHANGE_ME

# Java keystore and trustore
KAFKA_CLIENT_KEYSTORE_PASSWORD=my_keystore_pass # CHANGE_ME
KAFKA_CLIENT_TRUSTSTORE_PASSWORD=my_truststore_pass # CHANGE_ME

# Only for Option A: SASL
KAFKA_CLIENT_SASL_USER=my_sasl_username # CHANGE_ME
KAFKA_CLIENT_SASL_PASSWORD=my_sasl_password # CHANGE_ME

# Only for Option B: mTLS
KAFKA_CLIENT_MTLS_CN=example.com # CHANGE_ME
KAFKA_CLIENT_MTLS_NAME=client-a # CHANGE_ME
KAFKA_CLIENT_MTLS_IP=172.20.10.28 # CHANGE_ME (Hint: $ hostname -I )
KAFKA_SSL_PRINCIPAL_MAPPING_RULES='RULE:^.*[Cc][Nn]=([a-zA-Z0-9\.-]*).*$/$1/L,DEFAULT'
```

> More about `KAFKA_SSL_PRINCIPAL_MAPPING_RULES` at https://charmhub.io/kafka/configure#ssl_principal_mapping_rules and https://docs.confluent.io/platform/current/kafka/authorization.html#configuration-options-for-customizing-tls-ssl-user-name

#### Root CA

If you are using the [tls-certificates-operator charm](https://charmhub.io/tls-certificates-operator) as a Root CA run the following:

```bash
# ---------- Root CA
JUJU_TLS_OPERTOR_APP=tls-certificates-operator
JUJU_TLS_OPERTOR_UNIT=0

juju show-unit $JUJU_TLS_OPERTOR_APP/$JUJU_TLS_OPERTOR_UNIT --format json | jq -r '.[]."relation-info"[]."application-data"."self_signed_ca_certificate" // empty' > ss_ca.pem

juju show-unit $JUJU_TLS_OPERTOR_APP/$JUJU_TLS_OPERTOR_UNIT --format json | jq -r '.[]."relation-info"[]."application-data"."self_signed_ca_private_key" // empty' > ss_ca.key

SS_KEY_PASSWORD=$(juju show-unit $JUJU_TLS_OPERTOR_APP/$JUJU_TLS_OPERTOR_UNIT --format json | jq -r '.[]."relation-info"[]."application-data"."self_signed_ca_private_key_password" // empty')
```

Else retrieve Root CA from your certs provider.

#### Server CA

```bash
# ---------- Server CA
juju show-unit kafka/0 --format json | jq -r '.[]."relation-info"[]."local-unit".data.ca // empty' > kafka_ca.pem
```

#### Keystore (Client Cert)

This creates a client cert signed by the server

```bash
# ---------- Keystore
keytool -keystore client.keystore.jks -alias client-key -validity $CERT_EXPIRATION_DAYS \
  -genkey -keyalg RSA -noprompt -storepass $KAFKA_CLIENT_KEYSTORE_PASSWORD \
  -dname "CN=$KAFKA_CLIENT_MTLS_CN" \
  -ext SAN=DNS:${KAFKA_CLIENT_MTLS_NAME},IP:${KAFKA_CLIENT_MTLS_IP}

keytool -keystore client.keystore.jks --alias client-key -certreq -file client.csr -storepass $KAFKA_CLIENT_KEYSTORE_PASSWORD
openssl x509 -req -CA ss_ca.pem -CAkey ss_ca.key -in client.csr -out client.pem -days $CERT_EXPIRATION_DAYS -CAcreateserial -passin pass:$SS_KEY_PASSWORD

# Some client applications require keystore in .p12 format
# client.keystore.jks -> client.keystore.p12
keytool -importkeystore \
  -srckeystore client.keystore.jks -srcstorepass $KAFKA_CLIENT_KEYSTORE_PASSWORD \
  -destkeystore client.keystore.p12 -deststoretype PKCS12 -deststorepass $KAFKA_CLIENT_KEYSTORE_PASSWORD \
  -srcalias client-key -destalias client-key
openssl pkcs12 -in client.keystore.p12 -nodes -nocerts -out client_private_key.pem --password pass:$KAFKA_CLIENT_KEYSTORE_PASSWORD

openssl genrsa -out client_key.pem 4096
openssl req -new -key client_key.pem -out client_csr.pem -subj "/C=US/ST=Denial/L=Springfield/O=Dis/CN=$KAFKA_CLIENT_MTLS_CN"
openssl x509 -req -CA ss_ca.pem -CAkey ss_ca.key -in client_csr.pem -out client_cert.pem -days $CERT_EXPIRATION_DAYS -CAcreateserial -passin pass:$SS_KEY_PASSWORD
cat ss_ca.pem client_cert.pem client_key.pem > client_chain.pem

openssl pkcs12 -export -in client_chain.pem \
 -out client.keystore.p12 -password pass:$KAFKA_CLIENT_KEYSTORE_PASSWORD \
 -name client-chain -noiter -nomaciter
```

#### Trustsore (Server Cert)

We will inject Root CA and Server CA into the truststore file:

```bash
# ---------- Truststore
keytool -keystore client.truststore.jks -storepass $KAFKA_CLIENT_TRUSTSTORE_PASSWORD -noprompt \
  -importcert -alias kafka-ca -file kafka_ca.pem
keytool -keystore client.truststore.jks -storepass $KAFKA_CLIENT_TRUSTSTORE_PASSWORD -noprompt \
  -importcert -alias CARoot -file ss_ca.pem
```

#### Checking certs validity

```bash
# ---------- Teting Certs validity
echo "Client certs in Keystore:"
keytool -list -keystore client.keystore.jks -storepass $KAFKA_CLIENT_KEYSTORE_PASSWORD -rfc | grep "Alias name"
keytool -list -keystore client.keystore.jks -storepass $KAFKA_CLIENT_KEYSTORE_PASSWORD -v | grep until

echo "Server certs in Truststore:"
keytool -list -keystore client.truststore.jks -storepass $KAFKA_CLIENT_TRUSTSTORE_PASSWORD -rfc | grep "Alias name"
keytool -list -keystore client.truststore.jks -storepass $KAFKA_CLIENT_TRUSTSTORE_PASSWORD -v | grep until
```

### Option A: SASL_SSL

This includes SASL autentication through SSL, which requires:

1. For SSL the client needs to trust the server certificates.
2. For SASL an username and password credential are required.

To create new users we are going to a SASL_SSL user admin credentials that are stored inside the Kafka server

```bash
# ---------- Option A: SASL_SSL
# Create User
juju ssh kafka/leader "
echo 'LOG: Creating KAFKA_CLIENT_SASL_USER=$KAFKA_CLIENT_SASL_USER'

sudo charmed-kafka.configs \
  --bootstrap-server $KAFKA_SERVERS_SASL \
  --command-config $SNAP_KAFKA_PATH/client.properties \
  --alter --entity-type=users \
  --entity-name=$KAFKA_CLIENT_SASL_USER \
  --add-config=SCRAM-SHA-512=[password=$KAFKA_CLIENT_SASL_PASSWORD]
"
```

```bash
# client-sasl.properties
echo "sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username=\"safefleet\" password=\"$KAFKA_CLIENT_SASL_PASSWORD\";" > client-sasl.properties
echo sasl.mechanism=SCRAM-SHA-512 >> client-sasl.properties
echo security.protocol=SASL_SSL >> client-sasl.properties
echo bootstrap.servers=$KAFKA_SERVERS_MTLS >> client-sasl.properties
echo ssl.truststore.location=$SNAP_KAFKA_PATH/client.truststore.jks >> client-sasl.properties
echo ssl.truststore.password=$KAFKA_CLIENT_TRUSTSTORE_PASSWORD >> client-sasl.properties
echo ssl.truststore.type=JKS >> client-sasl.properties
echo ssl.keystore.location=$SNAP_KAFKA_PATH/client.keystore.p12 >> client-sasl.properties
echo ssl.keystore.password=$KAFKA_CLIENT_KEYSTORE_PASSWORD >> client-sasl.properties
echo ssl.keystore.type=PKCS12 >> client-sasl.properties
echo ssl.client.auth=none >> client-sasl.properties
```

### Option B: mTLS

This is a mutual TLS communication which means:

1. The client needs to trust the server certificates.
2. Instead of username and passwords, the client needs its own certificate signed by the server for the authentication.

```bash
juju config kafka ssl_principal_mapping_rules=$KAFKA_SSL_PRINCIPAL_MAPPING_RULES
```

```bash
# ---------- Option B: mTLS
juju ssh kafka/leader "

sudo charmed-kafka.configs \
  --bootstrap-server $KAFKA_SERVERS_SASL \
  --command-config $SNAP_KAFKA_PATH/client.properties \
  --alter --entity-type=users \
  --entity-name=$KAFKA_CLIENT_MTLS_CN \
"
```

```bash
# client-mtls.properties
echo security.protocol=SSL > client-mtls.properties
echo bootstrap.servers=$KAFKA_SERVERS_MTLS >> client-mtls.properties
echo ssl.truststore.location=$SNAP_KAFKA_PATH/client.truststore.jks >> client-mtls.properties
echo ssl.truststore.password=$KAFKA_CLIENT_TRUSTSTORE_PASSWORD >> client-mtls.properties
echo ssl.truststore.type=JKS >> client-mtls.properties
echo ssl.keystore.location=$SNAP_KAFKA_PATH/client.keystore.p12 >> client-mtls.properties
echo ssl.keystore.password=$KAFKA_CLIENT_KEYSTORE_PASSWORD >> client-mtls.properties
echo ssl.keystore.type=PKCS12 >> client-mtls.properties
echo ssl.client.auth=none >> client-mtls.properties
```

## Authorization

### Manage Authorization through ACLs

In this **example** we will be granting read and write privileges `KAFKA_CLIENT_SASL_USER` over _group_, _topic_ and _transaction_ resources and read only permissions to `KAFKA_CLIENT_MTLS_CN`.

Notice you can create multiple SASL or multiple mTLS users and each can have their own set of privileges.
You can also distribute one credential set to a group of multiple clients.

```bash
juju ssh kafka/leader "
echo 'LOG: Creating ACLs for SASL user'
sudo charmed-kafka.acls --bootstrap-server $KAFKA_SERVERS_SASL --command-config $SNAP_KAFKA_PATH/client.properties \
  --add --allow-principal User:$KAFKA_CLIENT_SASL_USER \
  --operation READ --operation DESCRIBE --group='*'

sudo charmed-kafka.acls --bootstrap-server $KAFKA_SERVERS_SASL --command-config $SNAP_KAFKA_PATH/client.properties \
  --add --allow-principal User:$KAFKA_CLIENT_SASL_USER \
  --operation READ --operation DESCRIBE --operation CREATE --operation WRITE --operation DELETE --operation ALTER --operation ALTERCONFIGS --topic='*'

sudo charmed-kafka.acls --bootstrap-server $KAFKA_SERVERS_SASL --command-config $SNAP_KAFKA_PATH/client.properties \
  --add --allow-principal User:$KAFKA_CLIENT_SASL_USER \
  --operation DESCRIBE --operation WRITE --transactional-id '*'
"
```

```bash
juju ssh kafka/leader "
echo 'LOG: Creating ACLs for MTLS user'
sudo charmed-kafka.acls --bootstrap-server $KAFKA_SERVERS_SASL --command-config $SNAP_KAFKA_PATH/client.properties \
  --add --allow-principal User:$KAFKA_CLIENT_MTLS_CN \
  --operation READ --operation DESCRIBE --group='*'

sudo charmed-kafka.acls --bootstrap-server $KAFKA_SERVERS_SASL --command-config $SNAP_KAFKA_PATH/client.properties \
  --add --allow-principal User:$KAFKA_CLIENT_MTLS_CN \
  --operation READ --operation DESCRIBE --topic='*'

sudo charmed-kafka.acls --bootstrap-server $KAFKA_SERVERS_SASL --command-config $SNAP_KAFKA_PATH/client.properties \
  --add --allow-principal User:$KAFKA_CLIENT_MTLS_CN \
  --operation DESCRIBE --transactional-id '*'
"
```

> Read more at https://docs.confluent.io/platform/current/kafka/authorization.html#operations

## Testing access

```bash
# ---------- Testing Kafka Access
KAFKA_TEST_TOPIC=TEST-TOPIC-A

sudo cp client.truststore.jks $SNAP_KAFKA_PATH/
sudo cp client.keystore.p12 $SNAP_KAFKA_PATH/
sudo cp client-mtls.properties $SNAP_KAFKA_PATH/
sudo cp client-sasl.properties $SNAP_KAFKA_PATH/

sudo chown snap_daemon:root $SNAP_KAFKA_PATH/client-mtls.properties
sudo chown snap_daemon:root $SNAP_KAFKA_PATH/client-sasl.properties
sudo chown snap_daemon:root $SNAP_KAFKA_PATH/client.keystore.p12
sudo chown snap_daemon:root $SNAP_KAFKA_PATH/client.truststore.jks

# mTLS
sudo charmed-kafka.topics --bootstrap-server $KAFKA_SERVERS_MTLS --command-config $SNAP_KAFKA_PATH/client-mtls.properties \
  --create --topic $KAFKA_TEST_TOPIC
sudo charmed-kafka.topics --list --bootstrap-server $KAFKA_SERVERS_MTLS --command-config $SNAP_KAFKA_PATH/client-mtls.properties

# SASL_SSL
sudo charmed-kafka.topics --bootstrap-server $KAFKA_SERVERS_SASL --command-config $SNAP_KAFKA_PATH/client-sasl.properties \
  --create --topic $KAFKA_TEST_TOPIC
sudo charmed-kafka.topics --list --bootstrap-server $KAFKA_SERVERS_SASL --command-config $SNAP_KAFKA_PATH/client-sasl.properties
```

> mTLS user will have permission denied to create a topic since that is how in this example we configured the authorization ACLs permissions.
