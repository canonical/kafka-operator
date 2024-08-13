Versions used for this integration example:

- LXD (v5.21.1)
- MicroK8s (v1.28.10)
- Kafka charm: built from [this feature PR](https://github.com/canonical/kafka-operator/pull/168), which adds Hydra integration

## Initial deployment

On microk8s, `metallb` addon is needed, this will allow Traefik ingress from the LXD model:

```bash
$ microk8s enable metallb:10.64.140.43-10.64.140.49
```

Loosely following the [Hydra tutorial](https://discourse.charmhub.io/t/topic/14087):

```bash
# On the microk8s controller
$ juju add-model iam

$ juju deploy hydra --channel=latest/edge --trust
$ juju deploy postgresql-k8s --channel 14/stable --trust --series jammy
$ juju deploy traefik-k8s --channel=latest/stable traefik-public
$ juju deploy traefik-k8s --channel=latest/stable traefik-admin
$ juju deploy self-signed-certificates --channel edge --config ca-common-name=test

# Once charms are deployed
$ juju integrate hydra postgresql-k8s
$ juju integrate hydra:public-ingress traefik-public
$ juju integrate hydra:admin-ingress traefik-admin
$ juju integrate self-signed-certificates traefik-public:certificates
$ juju integrate self-signed-certificates traefik-admin:certificates

$ juju offer admin/iam.hydra:oauth
$ juju offer admin/iam.self-signed-certificates:certificates
```

Kafka setup:

```bash
# On the lxd controller
$ juju add-model kafka

$ juju deploy zookeeper --channel 3/edge
$ juju deploy ./*charm  # kafka charm built from oauth feature PR
$ juju integrate zookeeper kafka

$ juju consume micro:admin/iam.hydra  # micro is the name of k8s controller
$ juju consume micro:admin/iam.self-signed-certificates

$ juju integrate kafka:certificates self-signed-certificates
$ juju integrate zookeeper self-signed-certificates
```

Once everything is settled, integrate Kafka and Hydra:

```bash
# On the lxd model
$ juju integrate kafka hydra
```

## Create a client on Hydra and request a token

```bash
# On iam model
$ code_client=$(juju run hydra/0 create-oauth-client --quiet scope="[profile,email,phone,offline]" grant-types="[client_credentials]" audience="[kafka]")
$ echo $code_client  # The client will look something similar to:
audience: '[''kafka'']' 
client-id: eeec2a88-52bf-46e6-85bf-d20cd832aa61 
client-secret: C1nycFCBFECMQ1-XsOPk0E4e_Y
grant-types: client_credentials
redirect-uris: ""
response-types: code
scope: profile email phone offline
token-endpoint-auth-method: client_secret_basic

$ juju run traefik-public/0 --quiet show-proxied-endpoints
proxied-endpoints: '{"hydra": {"url": "https://10.64.140.44/iam-hydra"}}' 

# Use public endpoint to request a token
# the user needed is made from <client-id:client-secret>
$ curl https://10.64.140.44/iam-hydra/oauth2/token -k -u eeec2a88-52bf-46e6-85bf-d20cd832aa61:C1nycFCBFECMQ1-XsOPk0E4e_Y -d "scope=profile" -d "grant_type=client_credentials" -d "audience=kafka" -s
{"access_token":"ory_at_b2pcwnwTpCVHPbxoU7L45isbRJhNdBbn91y4Ex0YNrA.easwGEfsTJ7VnNfER2svIMHwen5ZzNXaVZm8i7QdLLg","expires_in":3599,"scope":"profile","token_type":"bearer"}
```

With this token, a client can now authenticate on Kafka using oAuth listeners.