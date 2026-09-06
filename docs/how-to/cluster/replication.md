---
myst:
  html_meta:
    description: "Set up Charmed Apache Kafka cluster replication with MirrorMaker - active-passive replication using Kafka Connect."
---

(how-to-cluster-replication)=
# Set up replication between charmed clusters

This How-To will cover how to set up cluster replication using MirrorMaker through
[Kafka Connect](https://kafka.apache.org/41/kafka-connect/overview/).

```{note}
For a brief explanation of how MirrorMaker works,
see the [MirrorMaker explanation](explanation-mirrormaker2-0) page.
```

## Prerequisites

To set up cluster replication we need:

- Two Charmed Apache Kafka clusters on a common substrate:
  - A source cluster to replicate from.
  - A target cluster to replicate to.
- A Charmed Kafka Connect cluster to run the MirrorMaker connectors.

```{note}
The best practice is to co-locate the Kafka Connect cluster with the target Apache Kafka cluster,
for example, in the same cloud region.
```

For guidance on how to set up Charmed Apache Kafka, please refer to the following resources:

- The [How to deploy guide](how-to-deploy-anywhere) for Charmed Apache Kafka
- The [Kafka Connect guide](how-to-use-kafka-connect-for-etl-workloads)

The commands below use the VM application names. For K8s, use `kafka-k8s`
applications and `kafka-connect-k8s` as shown in the synchronized command tabs.

## Set up active-passive replication

The [MirrorMaker integrator charm](https://charmhub.io/mirrormaker-connect-integrator)
manages tasks on a Charmed Kafka Connect cluster that replicates data from an active
Apache Kafka cluster to a passive cluster.

Check the status of deployed applications by running `juju status`. The
following VM output illustrates the expected application state; Kubernetes
output uses pod addresses and omits the machine column:

```text
Model  Controller  Cloud/Region         Version  SLA          Timestamp
k      vms         localhost/localhost  3.6.3    unsupported  10:45:37+02:00

App            Version  Status  Scale  Charm          Channel       Rev  Exposed  Message
active         3.9.0    active      1  kafka          3/stable      240  no
passive        3.9.0    active      1  kafka          3/stable      240  no
kafka-connect           active      1  kafka-connect  latest/edge    20  no

Unit              Workload  Agent  Machine  Public address  Ports           Message
active/0*         active    idle   0        10.86.75.171    19092/tcp
passive/0*        active    idle   1        10.86.75.153    9092,19092/tcp
kafka-connect/0*  active    idle   2        10.86.75.45     8083/tcp
```

The `active` cluster serves as a source and `passive` as a target for replication.

Integrate Kafka Connect with the passive cluster (as recommended for active-passive replication):

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```bash
juju integrate kafka-connect passive
```

````

````{tab-item} K8s
:sync: k8s

```bash
juju integrate kafka-connect-k8s passive
```

````

`````

## Deploy a MirrorMaker integrator

First, deploy the MirrorMaker integrator charm:

```bash
juju deploy mirrormaker-connect-integrator mirrormaker
```

After some time the app should show up in the model as blocked:

```text
Unit              Workload  Agent  Machine  Public address  Ports           Message
mirrormaker/0*    blocked   idle   4        10.86.75.16                     Integrator not ready to start, check if all relations are setup successfully
```

Set up the necessary relations:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```bash
juju integrate kafka-connect mirrormaker
juju integrate mirrormaker:source active
juju integrate mirrormaker:target passive
```

````

````{tab-item} K8s
:sync: k8s

```bash
juju integrate kafka-connect-k8s mirrormaker
juju integrate mirrormaker:source active
juju integrate mirrormaker:target passive
```

````

`````

After some time, the `mirrormaker` application should show up as `active/idle`
in `juju status`. The following example is from a VM model:

```text
Model  Controller  Cloud/Region         Version  SLA          Timestamp
k      vms         localhost/localhost  3.6.3    unsupported  10:59:37+02:00

App            Version  Status  Scale  Charm          Channel       Rev  Exposed  Message
active         3.9.0    active      1  kafka          3/stable      240  no       
kafka-connect           active      1  kafka-connect  latest/edge    20  no       
mirrormaker             active      1  mirrormaker                    0  no       Task Status: UNASSIGNED
passive        3.9.0    active      1  kafka          3/stable      240  no       

Unit              Workload  Agent  Machine  Public address  Ports           Message
active/0*         active    idle   0        10.86.75.171    9092,19092/tcp  
kafka-connect/0*  active    idle   2        10.86.75.45     8083/tcp        
mirrormaker/0*    active    idle   3        10.86.75.189    8080/tcp        Task Status: UNASSIGNED
passive/0*        active    idle   1        10.86.75.153    9092,19092/tcp  
```

```{note}
Task status might show as UNASSIGNED since there are no replication tasks running yet. 
If the active Kafka cluster is idle, this is expected. 
The task status will change to `RUNNING` once the replication tasks are created and started.
```

With this, the deployment is complete. The Charmed Kafka Connect cluster will now start tasks to replicate data from the active cluster to the passive cluster.

## Set up active-active replication

MirrorMaker allows for a deployment where both clusters are active. This means that data can be replicated from both clusters to each other. This is done by creating a MirrorMaker connector for each cluster. Two flows are needed in this scenario, one from cluster A to cluster B and one from cluster B to cluster A.

In essence, it is equivalent to do two active-passive deployments, one for each direction. 

We recommend having two Kafka Connect deployments ready, one on each end of the replication.

### Deployment

To ensure that the topics are prefixed with the cluster name and do not collide with each other, deploy two different MirrorMaker integrators with the configuration option `prefix_topics=true`:

```bash
juju deploy mirrormaker-connect-integrator --config prefix_topics=true mirrormaker-a-b
juju deploy mirrormaker-connect-integrator --config prefix_topics=true mirrormaker-b-a
```

Check the status of deployed applications by running `juju status`. The
following example is from a VM model; Kubernetes output uses pod addresses and
the deployed charms are `kafka-k8s` and `kafka-connect-k8s`:

```text
Model  Controller  Cloud/Region         Version  SLA          Timestamp
k      vms         localhost/localhost  3.6.3    unsupported  10:59:37+02:00

App              Version  Status  Scale  Charm          Channel       Rev  Exposed  Message
kafka-a          3.9.0    active      1  kafka          3/stable      240  no       
kafka-b          3.9.0    active      1  kafka          3/stable      240  no       
kafka-connect-a           active      1  kafka-connect  latest/edge    20  no       
kafka-connect-b           active      1  kafka-connect  latest/edge    20  no       
mirrormaker-a-b           active      1  mirrormaker                   0  no       Task Status: UNASSIGNED
mirrormaker-b-a           active      1  mirrormaker                   0  no       Task Status: UNASSIGNED

Unit                Workload  Agent  Machine  Public address  Ports           Message
kafka-a/0*          active    idle   0        10.86.75.171    9092,19092/tcp  
kafka-b/0*          active    idle   1        10.86.75.153    9092,19092/tcp  
kafka-connect-a/0*  active    idle   2        10.86.75.45     8083/tcp        
kafka-connect-b/0*  active    idle   2        10.86.75.46     8083/tcp        
mirrormaker-a-b/0*  active    idle   3        10.86.75.189    8080/tcp        Task Status: UNASSIGNED
mirrormaker-b-a/0*  active    idle   3        10.86.75.190    8080/tcp        Task Status: UNASSIGNED
```

Then the integrations needed should be done like follows:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```bash
# active-passive  A -> B
juju integrate kafka-connect-b kafka-b
juju integrate kafka-connect-b mirrormaker-a-b
juju integrate mirrormaker-a-b:source kafka-a
juju integrate mirrormaker-a-b:target kafka-b

# active-passive  B -> A
juju integrate kafka-connect-a kafka-a
juju integrate kafka-connect-a mirrormaker-b-a
juju integrate mirrormaker-b-a:source kafka-b
juju integrate mirrormaker-b-a:target kafka-a
```

````

````{tab-item} K8s
:sync: k8s

```bash
# active-passive A -> B
juju integrate kafka-connect-k8s-b kafka-k8s-b
juju integrate kafka-connect-k8s-b mirrormaker-a-b
juju integrate mirrormaker-a-b:source kafka-k8s-a
juju integrate mirrormaker-a-b:target kafka-k8s-b

# active-passive B -> A
juju integrate kafka-connect-k8s-a kafka-k8s-a
juju integrate kafka-connect-k8s-a mirrormaker-b-a
juju integrate mirrormaker-b-a:source kafka-k8s-b
juju integrate mirrormaker-b-a:target kafka-k8s-a
```

````

`````

With this, the deployment is complete. There will be two bidirectional
replication flows between the A and B applications (`kafka-a`/`kafka-b` on VM,
or `kafka-k8s-a`/`kafka-k8s-b` on Kubernetes). Topics are prefixed with the
source application name so that they do not collide. For example, a `demo`
topic created on VM application `kafka-a` is replicated to `kafka-b` as
`kafka-a.replica.demo`, and vice versa.
