(how-to-create-mtls-client-credentials)=
# Use mTLS for clients

Requirements:

- Charmed Apache Kafka cluster up and running
- [Encryption enabled](how-to-enable-encryption)
- [{spellexception}`Java Runtime Environment (JRE)`](https://ubuntu.com/tutorials/install-jre#1-overview) installed
- [`charmed-kafka` snap](https://snapcraft.io/charmed-kafka) installed
- [jq](https://snapcraft.io/jq) installed

This guide includes step-by-step instructions on how to create mTLS credentials for a client application to be able to connect to a Charmed Apache Kafka cluster.

## Create mTLS client credentials

Each Apache Kafka mTLS client needs its own TLS certificate, which should be trusted by the charmed Apache Kafka application. In a typical production environment, certificates are issued either by the organization's PKI infrastructure, or trusted Certificate Authorities (CAs). For the sake of this guide, we will generate self-signed certificates.

To generate a self-signed certificate in one prompt, use the following command:

```bash
openssl req -new -newkey rsa:4096 -days 365 -nodes -x509 -keyout client.key -out client.pem -subj "/C=US/ST=Denial/L=Springfield/O=Dis/CN=TestClient"
```

## Create mutual trust relation: server -> client

In order for the mTLS client to be able to communicate with the server (broker), the client should trust the broker's identity, and the broker should trust the client's identity. First, create the trust relation between the broker and the client.

To trusts client certificates, the Apache Kafka charm's `trusted-certifcate` relation interface could be used. In order to integrate with that, you can deploy the `tls-certificates-operator` application and configure it to use the generated client certificate.

```bash
juju deploy tls-certificates-operator \
    --config generate-self-signed-certificates=false \
    --config ca-certificate=$(base64 -w0 client.pem) \
    --config certificate=$(base64 -w0 client.pem) \
    mtls-app
```

Next, integrate the operator application with the charmed Apache Kafka application via the `trusted-certificate` interface:

```bash
juju integrate kafka:trusted-certificate mtls-app
```

## Retrieve broker's CA certificate

The client needs to trust the broker's certificate. If you have followed the [Enable Encryption](how-to-enable-encryption) tutorial, you are using the `self-signed-certificates` charmed operator and can retrieve the root CA certificate executing the following command:

```bash
juju run self-signed-certificates/0 get-ca-certifictae
```

The result would be like below:

```text
Running operation 3 with 1 task
  - task 4 on unit-self-signed-certificates-0

Waiting for task 4...
ca-certificate: |-
  -----BEGIN CERTIFICATE-----
  MIIDTTCCAjWgAwIBAgIUVKaEiZ0fKnWDOvlap16dZtA6fWkwDQYJKoZIhvcNAQEL
  BQAwLDEqMCgGA1UEAwwhc2VsZi1zaWduZWQtY2VydGlmaWNhdGVzLW9wZXJhdG9y
  MB4XDTI1MDYxOTA4NTgyOFoXDTI2MDYxOTA4NTgyOFowLDEqMCgGA1UEAwwhc2Vs
  Zi1zaWduZWQtY2VydGlmaWNhdGVzLW9wZXJhdG9yMIIBIjANBgkqhkiG9w0BAQEF
  AAOCAQ8AMIIBCgKCAQEAnKCNGgoe/d60W/QGKnWuzFQ+S/1ol2+GaMzg7eyklq2h
  8zcT5YxkNIdY91awre09gvOERp3rrhumXgj72igufKjAoGn+M+xYiTC3cyiQq5SR
  2f7UvgCvufawNBeQEFMOJ/Oih3aBJujOUx4wTO2AX6G7+U7JLfqJEjW1ZzoMGJx1
  5Keyn4oXWTfylUkF+1QS6Nb5NNpjx5iFeSmCNU6i/P5p37m4xbb9L5r2feepU3N/
  iESqlLhEDUtvV0/IXVCIe23Dx5tNxqZoe4DlQTK1NxJ5Zb25c2lV6MfRS57T2nGU
  0VIMEkbrJ7Sc2CJnFhqJYR+81xGFtGjdfkC4d/AnRwIDAQABo2cwZTAfBgNVHQ4E
  GAQWBBRV19sdiADtRwc4UFUej0ao03KrGzAhBgNVHSMEGjAYgBYEFFXX2x2IAO1H
  BzhQVR6PRqjTcqsbMA4GA1UdDwEB/wQEAwICpDAPBgNVHRMBAf8EBTADAQH/MA0G
  CSqGSIb3DQEBCwUAA4IBAQBSe2nUHoLA5Snn7R+r/Jp+agBjFAHT0LslULG0z7/s
  GCo2/W84q2KOlDP1kUJ0C6JBeS1BZTd/ZzAuHBmCWkwOOmQnHCvzT3vxdLuKOab1
  tdGZg0nvxiU1FDSkTchMccmeUMRk3aKzrYUMNg2PLxl2u0GdJhmYjhtARUte3nzo
  ufPtyMx80lOEK02O8vzgwYidVr7xplbg8SdLKbGwMLH03Wv3w7ew9kN743HbT8AM
  nx4xSLCybz3upJpRMXXkIenf7Rr7eDp3s4deAbGcvCo6B/XDeBOkSv8Sl7CsSejm
  05qe06cC/6/K45CzOrWRwr4q5m6ENK/UT5fuOLFIoVJS
  -----END CERTIFICATE-----
```

Copy the certificate content into a file named `server.pem` and save it. You can also do that using a single command:

```bash
juju run self-signed-certificates/0 get-ca-certificate --format json | jq -r '."self-signed-certificates/0"."results"."ca-certificate"' > server.pem
```

## Create mutual trust relation: client -> server

Depending on the type of the client application, there might be different ways to trust. In this guide, we are using the console-based apps shipped with the `charmed-kafka` snap, which depend on java keystore/trustsores. Follow the steps below to create necessary Java keystore and truststore artifacts for the client application:

### Create client's keystore

Create the client's keystore using the following commands:

```bash
# Java keystore and truststore passwords
KAFKA_CLIENT_KEYSTORE_PASSWORD=changeme

# create client's certificate chain
cat client.pem client.key > client_chain.pem

# create PKCS12 keystore from chain and name it: client.keystore.p12
openssl pkcs12 -export -in client_chain.pem \
-out client.keystore.p12 -password pass:$KAFKA_CLIENT_KEYSTORE_PASSWORD \
-name client -noiter -nomaciter
```

### Create client's truststore

Trust the broker's CA certificate by importing it into a Java truststore using the following command

```bash
KAFKA_CLIENT_TRUSTSTORE_PASSWORD=changeme

# import broker's certificate into the truststor and name it: client.truststsore.jks
keytool -keystore client.truststore.jks -storepass $KAFKA_CLIENT_TRUSTSTORE_PASSWORD -noprompt \
  -importcert -alias server -file server.pem
```

### Check certificates validity

You can list the certificates loaded into client's keystore and truststore using the following commands:

```bash

# ---------- Check certs validity
echo "Client certs in Keystore:"
keytool -list -keystore client.keystore.p12 -storepass $KAFKA_CLIENT_KEYSTORE_PASSWORD -rfc | grep "Alias name"
keytool -list -keystore client.keystore.p12 -storepass $KAFKA_CLIENT_KEYSTORE_PASSWORD -v | grep until

echo "Server certs in Truststore:"
keytool -list -keystore client.truststore.jks -storepass $KAFKA_CLIENT_TRUSTSTORE_PASSWORD -rfc | grep "Alias name"
keytool -list -keystore client.truststore.jks -storepass $KAFKA_CLIENT_TRUSTSTORE_PASSWORD -v | grep until
```

## Define the client's credentials on the Apache Kafka cluster

Since you are using TLS certificates for authentication, you need to provide a way to map the client's certificate to usernames defined on the Apache Kafka cluster.

In charmed Apache Kafka, this could be done using the `ssl_principal_mapping_rules` config option, which defines how the certificate's common name is translated into a username, using a handy regex syntax (refer to [Apache Kafka's official documentation](https://kafka.apache.org/documentation/#security_authz_ssl) for more details on the syntax):

```bash
# Map the CN on the cert to be considered the principal (username)
juju config kafka ssl_principal_mapping_rules='RULE:^.*[Cc][Nn]=([a-zA-Z0-9\.-]*).*$/$1/L,DEFAULT'
```

This command will trigger a rolling restart of the charmed Apache Kafka application. Once the application settles to `active|idle` status, you can proceed to the next step.

## Add authorisation rules via ACLs for the client

Grant read and write privileges to the mTLS client user over _group_, _topic_ and _transaction_ resources:

```bash
# Apache Kafka Broker connection info
BROKER_IP=$(juju show-unit kafka/0 --format json | jq -r '."kafka/0"."public-address"')
KAFKA_SERVERS_SASL="$BROKER_IP:19093"
KAFKA_SERVERS_MTLS="$BROKER_IP:9094"

# Client certificate's common name, this should be all lower-case because of the L suffix in ssl_principal_mapping_rules
KAFKA_CLIENT_MTLS_CN=testclient

SNAP_KAFKA_PATH=/var/snap/charmed-kafka/current/etc/kafka

juju ssh kafka/leader "
sudo charmed-kafka.acls --bootstrap-server $KAFKA_SERVERS_SASL --command-config $SNAP_KAFKA_PATH/client.properties \
--add --allow-principal User:$KAFKA_CLIENT_MTLS_CN \
--operation READ --operation DESCRIBE --group='*'

sudo charmed-kafka.acls --bootstrap-server $KAFKA_SERVERS_SASL --command-config $SNAP_KAFKA_PATH/client.properties \
--add --allow-principal User:$KAFKA_CLIENT_MTLS_CN \
--operation READ --operation DESCRIBE --operation CREATE --operation WRITE --operation DELETE --operation ALTER --operation ALTERCONFIGS --topic=TEST

sudo charmed-kafka.acls --bootstrap-server $KAFKA_SERVERS_SASL --command-config $SNAP_KAFKA_PATH/client.properties \
--add --allow-principal User:$KAFKA_CLIENT_MTLS_CN \
--operation DESCRIBE --operation WRITE --transactional-id '*'
"
```

## Test access

Create a file called `client-mtls.properties` with the following configuration:

```bash
cat <<EOF > client-mtls.properties
security.protocol=SSL
bootstrap.servers=$KAFKA_SERVERS_MTLS
ssl.truststore.location=$SNAP_KAFKA_PATH/client.truststore.jks
ssl.truststore.password=$KAFKA_CLIENT_TRUSTSTORE_PASSWORD
ssl.truststore.type=JKS
ssl.keystore.location=$SNAP_KAFKA_PATH/client.keystore.p12
ssl.keystore.password=$KAFKA_CLIENT_KEYSTORE_PASSWORD
ssl.keystore.type=PKCS12
ssl.client.auth=required
EOF
```

Test the client's access using below commands to create a topic named `TEST`:

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
--create --topic TEST

# You should see: Created topic TEST.

sudo charmed-kafka.topics --list --bootstrap-server $KAFKA_SERVERS_MTLS --command-config $SNAP_KAFKA_PATH/client-mtls.properties
```

