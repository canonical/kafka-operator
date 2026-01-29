(how-to-enable-oauth)=

# Enable OAuth through Canonical Identity Platform

Charmed Apache Kafka can integrate with charmed OAuth providers through the `oauth` interface.
In this guide, you will integrate Charmed Apache Kafka with Canonical Identity Platform.

To follow this guide, you need the following snaps installed:

- LXD `5.21/stable`
- MicroK8s `1.32-strict/stable` with `metallb` addon enabled
- Terraform `latest/stable`
- Juju `3.6/stable`
- jq `latest/stable`
- Charmed Apache Kafka `4/edge`

Moreover, it is assumed that you have Juju bootstrapped on both LXD and MicroK8s.
The environment variables `LXD_CONTROLLER` and `MICROK8S_CONTROLLER` in this guide
refer to the LXD and MicroK8s Juju controllers respectively.

## Deploy Canonical Identity Platform

Switch to the MicroK8s controller using `juju switch $MICROK8S_CONTROLLER` command and
follow the [Canonical Identity Platform's deployment tutorial](https://charmhub.io/topics/canonical-identity-platform/tutorials/e2e-tutorial)
to deploy and activate the necessary charmed operators and integrations:

```bash
git clone --branch v1.0.0 https://github.com/canonical/iam-bundle-integration.git
cd iam-bundle-integration
terraform -chdir=examples/tutorial init
terraform -chdir=examples/tutorial apply -auto-approve
```

## Deploy and integrate Charmed Apache Kafka

Switch to the LXD controller using `juju switch $LXD_CONTROLLER` command and
deploy Charmed Apache Kafka following the [Deploy Apache Kafka tutorial](tutorial-deploy):

```bash
juju add-model kafka-oauth
juju deploy kafka -n 3 --channel 4/edge --config roles="controller" controller
juju deploy kafka -n 3 --channel 4/edge --config roles="broker"
juju integrate kafka:peer-cluster-orchestrator controller:peer-cluster
```

Now consume the necessary TLS and OAuth offers:

```bash
juju consume $MICROK8S_CONTROLLER:admin/iam.oauth-offer
juju consume $MICROK8S_CONTROLLER:admin/core.certificates
```

And integrate Apache Kafka application with the consumed offers:

```bash
juju integrate kafka:certificates certificates
juju integrate kafka oauth-offer
```

And wait a couple of minutes for the applications to settle to `active|idle` state.

## Test OAuth on Apache Kafka

To test the OAuth setup, we will use the CLI client shipped with the Charmed Apache Kafka snap.
It is assumed that you have the Charmed Apache Kafka 4 snap installed on your system.

First, create an OAuth client using the `hydra` application's `create-oauth-client` action:

```bash
CLIENT_CREDS=$(juju run \
  -m $MICROK8S_CONTROLLER:iam \
  --format json \
  --quiet \
  hydra/0 \
  create-oauth-client \
  scope="[profile,email,phone,offline]" \
  grant-types="[client_credentials]" \
  audience="[kafka]"
)
```

The `CLIENT_CREDS` variable contains OAuth client credentials, including `client-id` and `client-secret`
required for [OAuth 2.0 Client Credentials authorisation flow](https://datatracker.ietf.org/doc/html/rfc6749#section-4.4).
Extract these into separate environment variables:

```bash
CLIENT_ID=$(echo $CLIENT_CREDS | jq -r '."hydra/0"."results"."client-id"')
CLIENT_SECRET=$(echo $CLIENT_CREDS | jq -r '."hydra/0"."results"."client-secret"')
```

You also need the OAuth token endpoint URI:

```bash
BASE_URI=$(juju run \
  --quiet \
  -m $MICROK8S_CONTROLLER:core \
  --format json \
  traefik-public/0 \
  show-proxied-endpoints | \
  jq '."traefik-public/0"."results"."proxied-endpoints"' | \
  jq -r 'fromjson | ."traefik-public"."url"'
)
TOKEN_URI="$BASE_URI/oauth2/token"
```

Next, you need to create a truststore for the client, and import the Apache Kafka and OAuth provider's
CA certificate into it. First, you need to retrieve the CA. If you are following this guide and using the
Canonical Identity Platform's Terraform bundle, this could be achieved using:

```bash
juju run -m $MICROK8S_CONTROLLER:core \
  --quiet \
  --format json \
  self-signed-certificates/0 \
  get-ca-certificate | \
  jq -r '."self-signed-certificates/0"."results"."ca-certificate"' | \
  sudo tee -a /var/snap/charmed-kafka/current/etc/kafka/ca-cert.pem
```

Now, create the truststore:

```bash
TRUSTSTORE_PATH="/var/snap/charmed-kafka/current/etc/kafka/oauth-client-truststore.jks"
TRUSTSTORE_PASSWORD="strongP4ss"
sudo charmed-kafka.keytool -import \
  -alias ca \
  -file /var/snap/charmed-kafka/current/etc/kafka/ca-cert.pem \
  -keystore $TRUSTSTORE_PATH \
  -storepass $TRUSTSTORE_PASSWORD \
  -noprompt
```

Finally, create the Apache Kafka CLI client configuration file:

```bash
cat > oauth-client.properties <<EOF
security.protocol=SASL_SSL
sasl.mechanism=OAUTHBEARER
sasl.jaas.config=org.apache.kafka.common.security.oauthbearer.OAuthBearerLoginModule required \\
  oauth.client.id="$CLIENT_ID" \\
  oauth.client.secret="$CLIENT_SECRET" \\
  oauth.token.endpoint.uri="$TOKEN_URI" \\
  oauth.scope="profile" \\
  oauth.ssl.truststore.location="$TRUSTSTORE_PATH" \\
  oauth.ssl.truststore.password="$TRUSTSTORE_PASSWORD" \\
  oauth.ssl.truststore.type="JKS" \\
  oauth.audience="kafka";
sasl.login.callback.handler.class=io.strimzi.kafka.oauth.client.JaasClientOauthLoginCallbackHandler
ssl.truststore.location=$TRUSTSTORE_PATH
ssl.truststore.password=$TRUSTSTORE_PASSWORD
EOF
sudo mv oauth-client.properties /var/snap/charmed-kafka/current/etc/kafka/
```

Now try to create a topic using the CLI client:

```bash
sudo charmed-kafka.topics \
  --command-config /var/snap/charmed-kafka/current/etc/kafka/oauth-client.properties \
  --bootstrap-server $KAFKA_BROKER_IP:9096 \
  --create \
  --topic test
```

The OAuth user should be able to authenticate, but you will see an `Authorization failed` error
since the user does not have the necessary permissions to create a topic.

To resolve the authorisation issue, you can use the `charmed-kafka.acls` command
to create the necessary ACLs for the OAuth user.
In this scenario, the username is identified by the value in `$CLIENT_ID` variable.
For more information on how to manage authorisation in Apache Kafka clusters, please consult the
[official documentation](https://kafka.apache.org/documentation/#security_authz_cli).

Sample command to add ACLs for the OAuth user:

```bash
juju ssh kafka/0 \
  sudo charmed-kafka.acls \
    --bootstrap-server $KAFKA_BROKER_IP:19093 \
    --command-config /var/snap/charmed-kafka/current/etc/kafka/client.properties \
    --add \
    --allow-principal=User:$CLIENT_ID \
    --operation READ \
    --operation WRITE \
    --operation CREATE \
    --topic test
```

You should see an output like the following:

```text
Adding ACLs for resource `ResourcePattern(resourceType=TOPIC, name=test, patternType=LITERAL)`: 
 	(principal=User:ebb3010e-d0a0-4335-aee6-105cf85ebbc0, host=*, operation=READ, permissionType=ALLOW)
	(principal=User:ebb3010e-d0a0-4335-aee6-105cf85ebbc0, host=*, operation=WRITE, permissionType=ALLOW)
	(principal=User:ebb3010e-d0a0-4335-aee6-105cf85ebbc0, host=*, operation=CREATE, permissionType=ALLOW)
```

Now repeat the topic creation command, and it should succeed now.
