# How to deploy Charmed Apache Kafka

[note type="caution"]
For K8s Charmed Apache Kafka, see the [Charmed Apache Kafka K8s documentation](/t/charmed-kafka-k8s-documentation-how-to-deploy/13266) instead.
[/note]

To deploy a Charmed Apache Kafka cluster on a bare environment, it is necessary to:

1. Set up a Juju Controller
2. Set up a Juju Model
3. Deploy Charmed Apache Kafka and Charmed Apache ZooKeeper
4. (Optionally) Create an external admin user

In the next subsections, we will cover these steps separately by referring to 
relevant Juju documentation and providing details on the Charmed Apache Kafka specifics.
If you already have a Juju controller and/or a Juju model, you can skip the associated steps.

## Juju controller setup

Make sure you have a Juju controller accessible from 
your local environment using the [Juju client snap](https://snapcraft.io/juju). 

List available controllers:
Make sure that the controller's back-end cloud is **not** K8s. 
The cloud information can be retrieved with the following command

```commandline
juju list-controllers
```

Switch to another controller if needed:

```commandline
juju switch <controller>
```

If there are no suitable controllers, create a new one:

```commandline
juju bootstrap <cloud> <controller>
```

where `<cloud>` -- the cloud to deploy controller to, e.g., `localhost`. For more information on how to set up a new cloud, see the [How to manage clouds](https:///t/1100) guide in Juju documentation.

For more Juju controller setup guidance, see the [How to manage controllers](/t/1111) guide in Juju documentation.

## Juju model setup

You can create a new Juju model using 

```commandline
juju add-model <model>
```

Alternatively, you can switch to any existing Juju model: 

```commandline
juju switch <model-name>
```

Make sure that the model is of a correct type (not `k8s`):

```commandline
juju show-model | yq '.[].type'
```

## Deploy Charmed Apache Kafka and Charmed Apache ZooKeeper

The Apache Kafka and Apache ZooKeeper charms can both be deployed as follows:

```commandline
$ juju deploy kafka --channel 3/stable -n <kafka-units> --trust
$ juju deploy zookeeper --channel 3/stable -n <zookeeper-units>
```

where `<kafka-units>` and `<zookeeper-units>` – the number of units to deploy for Apache Kafka and Apache ZooKeeper. We recommend values of at least `3` and `5` respectively.

[note]
The `--trust` option is needed for the Apache Kafka application if NodePort is used. For more information about the trust options usage, see the [Juju documentation](/t/5476#heading--trust-an-application-with-a-credential). 
[/note]

Connect Apache ZooKeeper and Apache Kafka by relating/integrating the charms:

```shell
$ juju relate kafka zookeeper
```

Check the status of the deployment:

```commandline
juju status
```

The deployment should be complete once all the units show `active` or `idle` status. 

## (Optional) Create an external admin users

Charmed Apache Kafka aims to follow the _secure by default_ paradigm. As a consequence, after being deployed the Apache Kafka cluster 
won't expose any external listener. 
In fact, ports are only opened when client applications are related, also 
depending on the protocols to be used.

[note]
For more information about the available listeners and protocols please refer to [this table](/t/13264). 
[/note]

It is however generally useful for most of the use cases to create a first admin user
to be used to manage the Apache Kafka cluster (either internally or externally). 

To create an admin user, deploy the [Data Integrator Charm](https://charmhub.io/data-integrator) with 
`extra-user-roles` set to `admin`:

```commandline
juju deploy data-integrator --channel stable --config topic-name=test-topic --config extra-user-roles=admin
```

... and relate it to the Apache Kafka charm:

```commandline
juju relate data-integrator kafka
```

To retrieve authentication information, such as the username and password, use:

```commandline
juju run data-integrator/leader get-credentials
```