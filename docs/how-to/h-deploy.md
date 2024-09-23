# How to deploy Charmed Kafka

To deploy a Charmed Kafka cluster on a bare environment, it is necessary to:

1. Set up a Juju Controller
2. Set up a Juju Model
3. Deploy Charmed Kafka and Charmed ZooKeeper
4. (Optionally) Create an external admin user

In the next subsections, we will cover these steps separately by referring to 
relevant Juju documentation and providing details on the Charmed Kafka specifics.
If you already have a Juju controller and/or a Juju model, you can skip the associated steps.

## Juju controller setup

Before deploying Kafka, make sure you have a Juju controller accessible from 
your local environment using the [Juju client snap](https://snapcraft.io/juju). 

The properties of your current controller can be listed using `juju show-controller`. 
Make sure that the controller's back-end cloud is **not** K8s. 
The cloud information can be retrieved with the following command

```commandline
juju show-controller | yq '.[].details.cloud'
```

> **IMPORTANT** If the cloud is `k8s`, please refer to the [Charmed Kafka K8s documentation](/t/charmed-kafka-k8s-documentation/10296) instead.

You can find more information on how to bootstrap and configure a controller for different 
clouds [here](https://juju.is/docs/juju/manage-controllers#heading--bootstrap-a-controller). 
Make sure you bootstrap a `machine` Juju controller. 

## Juju model setup

You can create a new Juju model using 

```
juju add-model <model>
```

Alternatively, you can use a pre-existing Juju model and switch to it by running the following command:

```
juju switch <model-name>
```

Make sure that the model is **not** a `k8s` type. The type of the model 
can be obtained by 

```
juju show-model | yq '.[].type'
```

> **IMPORTANT** If the model is `k8s`, please refer to the [Charmed Kafka K8s documentation](https://discourse.charmhub.io/t/charmed-kafka-k8s-documentation/10296) instead.

## Deploy Charmed Kafka and Charmed ZooKeeper

The Kafka and ZooKeeper charms can both be deployed as follows:

```shell
$ juju deploy kafka --channel 3/stable -n <kafka-units> --trust
$ juju deploy zookeeper --channel 3/stable -n <zookeeper-units>
```

where `<kafka-units>` and `<zookeeper-units>` – the number of units to deploy for Kafka and ZooKeeper. We recommend values of at least `3` and `5` respectively.

> **NOTE** The `--trust` option is needed for the Kafka application if NodePort is used. For more information about the trust options usage, see the [Juju documentation](/t/5476#heading--trust-an-application-with-a-credential). 

After this, it is necessary to connect them:

```shell
$ juju relate kafka zookeeper
```

Once all the units show as `active|idle` in the `juju status` output, the deployment 
should be ready to be used. 

## (Optional) Create an external admin users

Charmed Kafka aims to follow the _secure by default_ paradigm. As a consequence, after being deployed the Kafka cluster 
won't expose any external listener. 
In fact, ports are only opened when client applications are related, also 
depending on the protocols to be used. Please refer to [this table](/t/charmed-kafka-documentation-reference-listeners/13264) for 
more information about the available listeners and protocols. 

It is however generally useful for most of the use-cases to create a first admin user
to be used to manage the Kafka cluster (either internally or externally). 

To create an admin user, deploy the [Data Integrator Charm](https://charmhub.io/data-integrator) with 
`extra-user-roles` set to `admin`

```shell
juju deploy data-integrator --channel stable --config topic-name=test-topic --config extra-user-roles=admin
```

and relate to the Kafka charm

```shell
juju relate data-integrator kafka
```

To retrieve authentication information such as the username, password, etc. use

```shell
juju run data-integrator/leader get-credentials
```