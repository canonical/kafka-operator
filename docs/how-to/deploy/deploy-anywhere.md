---
myst:
  html_meta:
    description: "Platform-independent guide to deploy Charmed Apache Kafka on VM or Kubernetes - set up Juju controller, model, and create admin users."
---

# How to deploy Charmed Apache Kafka

This guide provides deployment instructions for Charmed Apache Kafka using the
Juju CLI, covering both the **IAAS/VM** operator and the **Kubernetes** operator.
Use the tabs below to switch between the two substrates -- your selection is
remembered as you scroll through the rest of the page.

Platform-specific steps are also available:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

- [AWS](how-to-deploy-on-aws)
- [Azure](how-to-deploy-on-azure)
- [Juju spaces](how-to-deploy-spaces)
- [Terraform](how-to-deploy-terraform)
````

````{tab-item} K8s
:sync: k8s

- [AWS](how-to-deploy-on-aws)
- [Azure](how-to-deploy-on-azure)
- [Juju spaces](how-to-deploy-spaces)
- [Terraform](how-to-deploy-terraform)
````

`````

(how-to-deploy-anywhere)=

To deploy a Charmed Apache Kafka cluster on a bare environment, it is necessary to:

1. Set up a Juju controller
2. Set up a Juju model
3. Deploy Charmed Apache Kafka
4. Create an external admin user

In the next subsections, we cover these steps separately by referring to
relevant Juju documentation and providing details on the Charmed Apache Kafka
specifics for each substrate. If you already have a Juju controller and/or a
Juju model, you can skip the associated steps.

## Juju controller setup

Make sure you have a Juju controller accessible from your local environment
using the [Juju client snap](https://snapcraft.io/juju).

List available controllers:

```shell
juju list-controllers
```

Switch to another controller if needed:

```shell
juju switch <controller>
```

If there are no suitable controllers, create a new one:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```shell
juju bootstrap <cloud> <controller>
```

Make sure that the controller's back-end cloud is **not** Kubernetes-based.
The cloud information can be retrieved with `juju list-controllers`.

`<cloud>` -- the cloud to deploy the controller to, e.g. `localhost` if using
a LXD cloud.
````

````{tab-item} K8s
:sync: k8s

```shell
juju bootstrap <cloud> <controller>
```

Make sure that the controller's back-end cloud **is** Kubernetes-based (e.g.
`microk8s`).

`<cloud>` -- the cloud to deploy the controller to.
````

`````

For more information on how to set up a new cloud, see the [How to manage clouds](https://documentation.ubuntu.com/juju/latest/howto/manage-clouds/index.html)
guide in the Juju documentation. For more controller setup guidance, see the
[How to manage controllers](https://documentation.ubuntu.com/juju/latest/howto/manage-controllers/)
guide.

## Juju model setup

You can create a new Juju model using:

```shell
juju add-model <model>
```

Alternatively, you can switch to any existing Juju model:

```shell
juju switch <model-name>
```

Make sure that the model is of the correct type:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```shell
juju show-model | yq '.[].type'
```

The type must **not** be `k8s`.
````

````{tab-item} K8s
:sync: k8s

```shell
juju show-model | yq '.[].type'
```

The type must be `k8s`.
````

`````

## Deploy Charmed Apache Kafka for production

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

Charmed Apache Kafka for production use-cases is deployed as follows:

```shell
juju deploy kafka -n <broker-units> --config roles=broker --channel 4/stable
juju deploy kafka -n <controller-units> --config roles=controller --channel 4/stable controller
```

- `<broker-units>` -- the number of units to deploy for Charmed Apache Kafka brokers
- `<controller-units>` -- the number of units to deploy for KRaft controllers
````

````{tab-item} K8s
:sync: k8s

Charmed Apache Kafka K8s for production use-cases is deployed as follows:

```shell
juju deploy kafka-k8s -n <broker-units> --config roles=broker --channel 4/edge --trust
juju deploy kafka-k8s -n <controller-units> --config roles=controller --channel 4/edge controller --trust
```

- `<broker-units>` -- the number of units to deploy for Charmed Apache Kafka K8s brokers
- `<controller-units>` -- the number of units to deploy for KRaft controllers

```{note}
The `--trust` flag is required so the charm can manage the Kubernetes resources
it needs (e.g. Services, StatefulSets).
```
````

`````

To maintain high-availability of topic partitions, `3+` broker units and `3` or
`5` controller units are recommended.

To exchange credentials and endpoints between the two clusters, integrate the
broker and controller applications:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```shell
juju integrate kafka:peer-cluster-orchestrator controller:peer-cluster
```
````

````{tab-item} K8s
:sync: k8s

```shell
juju integrate kafka-k8s:peer-cluster-orchestrator controller:peer-cluster
```
````

`````

Check the status of the deployment:

```shell
juju status
```

The deployment should be complete once all the units show `active` and `idle` status.

## (Alternative) Deploy Charmed Apache Kafka for testing

In order to save resources for very-small, non-production test and staging
clusters, it is possible to co-locate both the KRaft controller services and
the broker services into a single application.

```{warning}
This is not recommended for any production deployments. Apache Kafka brokers
rely on the KRaft controllers to coordinate -- if both services go down at the
same time, the risk of cluster instability increases.
```

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

Charmed Apache Kafka for testing use-cases is deployed as follows:

```shell
juju deploy kafka -n <kafka-units> --config roles=broker,controller --channel 4/stable
```

- `<kafka-units>` -- the number of units to deploy for Charmed Apache Kafka
````

````{tab-item} K8s
:sync: k8s

Charmed Apache Kafka K8s for testing use-cases is deployed as follows:

```shell
juju deploy kafka-k8s -n <kafka-units> --config roles=broker,controller --channel 4/edge --trust
```

- `<kafka-units>` -- the number of units to deploy for Charmed Apache Kafka K8s
````

`````

Check the status of the deployment:

```shell
juju status
```

The deployment should be complete once all the units show `active` or `idle` status.

## (Optional) Create an external admin user

Charmed Apache Kafka aims to follow the _secure by default_ paradigm. As a
consequence, after being deployed the Apache Kafka cluster won't expose any
external listeners -- the cluster will be unreachable. Ports are only opened
when client applications are integrated.

```{note}
For more information about the available listeners and protocols, refer to
[this table](reference-broker-listeners).
```

For most cluster administrators, it may be most helpful to create a user with
the `admin` role, which has `super.user` permissions on the Apache Kafka cluster.

To create an admin user, deploy the [Data Integrator charm](https://charmhub.io/data-integrator)
with `extra-user-roles` set to `admin`:

```shell
juju deploy data-integrator --config topic-name="__admin-user" --config extra-user-roles="admin"
```

Now, integrate it with the Apache Kafka charm:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```shell
juju integrate data-integrator kafka
```
````

````{tab-item} K8s
:sync: k8s

```shell
juju integrate data-integrator kafka-k8s
```
````

`````

To retrieve authentication information, such as the username and password, use:

```shell
juju run data-integrator/leader get-credentials
```
