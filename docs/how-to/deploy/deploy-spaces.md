# Deploy on Juju spaces

The Charmed Apache Kafka operator supports [Juju spaces](https://documentation.ubuntu.com/juju/latest/reference/space/index.html) to separate network traffic for:

- **Internal communications**, including inter-broker and broker-to-controller communications.
- **Client**, including traffic between broker and clients (producers and consumers).

## Prerequisites

* Charmed Apache Kafka 4
* Configured network spaces
  * See [Juju | `add-space` command reference](https://documentation.ubuntu.com/juju/latest/reference/juju-cli/list-of-juju-cli-commands/add-space/)

## Deploy

On application deployment, constraints are required to ensure the unit(s) have address(es) on the specified network space(s), and endpoint binding(s) for the space(s).

For example, consider the output of `juju spaces` command is like below:

```text
Name      Space ID  Subnets
alpha     0         10.148.97.0/24
client    1         10.0.0.0/24
peers     2         10.10.10.0/24
```

The space `alpha` is the default and cannot be removed. Two other spaces are configured for client and peer (internal) communications. To deploy Charmed Apache Kafka using the mentioned spaces:

```bash
juju deploy kafka --channel 4/edge \
  --constraints spaces=client,peers \
  --bind "cluster=peers kafka-client=clients"
```

```{caution}
Currently there's no support for the `juju bind` command. Network space binding must be defined at deploy time only.
```

To communicate with the deployed Apache Kafka cluster, a client application must use the `client` space in the model or a space on the same subnet in another model. For example:

```bash
juju deploy kafka-test-app \
  --constraints spaces=client \
  --bind kafka-cluster=client
```

The two application can then be integrated using:

```bash
juju integrate kafka kafka-test-app
```

As a result, the client application will receive network endpoints on the subnets prescribed by the Juju space `client`, while the Apache Kafka cluster will use the `peers` space for internal communications. In the previous example, those are `10.0.0.0/24` and `10.10.10.0/24` subnets respectively. 
