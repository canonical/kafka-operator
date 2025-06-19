(how-to-deploy-kraft-mode)=
# How to set up KRaft mode

```{caution}
This feature is experimental and not production-ready. UX can change significantly in the upcoming months.
```

Apache Kafka Raft (KRaft) is a consensus protocol introduced to remove ZooKeeper dependency from a Kafka deployment.
This guide provides step-by-step instructions to configure Kafka in [KRaft mode](https://kafka.apache.org/documentation/#kraft) introduced in [KIP-500](https://cwiki.apache.org/confluence/display/KAFKA/KIP-500%3A+Replace+ZooKeeper+with+a+Self-Managed+Metadata+Quorum).

## Prerequisites

Follow the first steps of the [How to deploy Charmed Apache Kafka](https://discourse.charmhub.io/t/charmed-kafka-documentation-how-to-deploy/13261) guide to set up the environment. Stop before deploying Charmed Apache Kafka and continue with the instructions below.

## Roles setup

A new **role** has been introduced to the charm, named `controller`. The application with this role assigned becomes a controller for the cluster. Using this role, the charm can be deployed either as a single app or multiple applications with a dedicated controller app. We recommend splitting controller tasks to a dedicated app.

### Single application deployment

To deploy Charmed Apache Kafka in KRaft mode as a single application, assign both `controller` and `broker` roles to the application when using the `juju deploy` command:

```shell
juju deploy kafka --channel 3/edge --config roles="broker,controller"
```

Once the unit is shown as `active|idle` in the `juju status` command output, the deployment should be ready to be used.

### Multiple applications deployment

To deploy Charmed Apache Kafka in KRaft mode as multiple applications, you need to split roles between applications.
First, deploy the applications: a dedicated cluster controller and a broker cluster with relevant roles:

```shell
juju deploy kafka --channel 3/edge --config roles="controller" controller
juju deploy kafka --channel 3/edge --config roles="broker" broker
```

Finally, integrate the applications with the `peer-cluster-orchestrator` and `peer-cluster` roles:

```shell
juju integrate broker:peer-cluster-orchestrator controller:peer-cluster
```

The deployment is complete when all the units are shown as `active|idle` in the `juju status` command output. 

## (Optional) Create an external admin user

```{note}
This step is normally done using `data-integrator`. However, the current ACL implementation has a bug where internal operations will fail on the integration step with the data integrator.
```

To create external users, use `juju ssh` to connect to a broker unit and use the `charmed-kafka.configs` bin command to create a new user:

```shell
juju ssh broker/0 -- sudo su
charmed-kafka.configs --alter --entity-type=users --entity-name=<admin-name> --add-config=SCRAM-SHA-512=[password=<admin-password>] --bootstrap-server <broker-ip>:9092 --command-config /var/snap/charmed-kafka/current/etc/kafka/admin.config
```

