# Deploy on Juju spaces

The Charmed Apache Kafka operator supports [Juju spaces](https://documentation.ubuntu.com/juju/latest/reference/space/index.html) to separate network traffic for:

- **Internal communication** - inter-broker and broker-to-controller communications.
- **Client** - broker to clients traffic.

## Prerequisites

* Charmed Apache Kafka 4
* Configured network spaces
  * See [Juju | How to manage network spaces](https://documentation.ubuntu.com/juju/latest/reference/juju-cli/list-of-juju-cli-commands/add-space/)

## Deploy

On application deployment, constraints are required to ensure the unit(s) have address(es) on the specified network space(s), and endpoint binding(s) for the space(s).

For example, with spaces configured for instance replication and client traffic:
```text
❯ juju spaces
Name      Space ID  Subnets
alpha     0         10.148.97.0/24
client    1         10.0.0.0/24
peers     2         10.10.10.0/24
```

The space `alpha` is the default and cannot be removed. To deploy Charmed Apache Kafka using the spaces:

```bash
juju deploy kafka --channel 4/edge \
  --constraints spaces=client,peers \
  --bind "peer=peers kafka-client=clients"
```

[note type=caution]
Currently there's no support for the juju `bind` command. Network space binding must be defined at deploy time only.
[/note]

Consequently, a client application must use the `client` space on the model, or a space for the same subnet in another model, for example:

```bash
juju deploy kafka-test-app \
  --constraints spaces=client \
  --bind kafka-cluster=client
```

The two application can be then related using:

```text
juju integrate kafka kafka-test-app
```

The client application will receive network endpoints on the `10.0.0.0/24` subnet, while the Apache Kafka cluster will use the 10.10.10.0/24 for internal communications.
