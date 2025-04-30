# Set up MirrorMaker cluster replication

This How-To will cover how to set up cluster replication using MirrorMaker through [Kafka Connect](https://kafka.apache.org/documentation/#connect).

The document will cover 


[note]
For more info on MirrorMaker, check the explanation section on MirrorMaker <!-- TODO: add link -->
[/note]


## Pre-requisites

To set up cluster replication we need:

- Two Charmed Apache Kafka clusters:
  - An "active" cluster to replicate from.
  - A "passive" cluster to replicate to.
  - A Charmed Kafka Connect cluster to run the MirrorMaker connectors.

For guidance on how to set up Charmed Apache Kafka, please refer to the following resources:
  - The [Charmed Apache Kafka Tutorial](/t/charmed-kafka-tutorial-overview/10571)
  - The [How to deploy guide](/t/charmed-apache-kafka-documentation-how-to-deploy/13261) for Charmed Apache Kafka
  - The [Charmed Kafka Connect Tutorial](/t/charmed-kafka-connect-tutorial-overview/) <!-- TODO: fill with Connect tutorial link -->



## Deploy a MirrorMaker integrator

The MirrorMaker integrator is a charm tasked with creating a relation between Kafka Connect, an active cluster and a passive cluster. It will deploy the MirrorMaker connectors to the Kafka Connect cluster, which will then replicate data from the active cluster to the passive cluster.

### Current deployment

At this point, the deployment should look like this:

```bash
Model  Controller  Cloud/Region         Version  SLA          Timestamp
k      vms         localhost/localhost  3.6.3    unsupported  10:45:37+02:00

App            Version  Status  Scale  Charm          Channel      Rev  Exposed  Message
active         3.9.0    active      1  kafka          3/edge       205  no
passive        3.9.0    active      1  kafka          3/edge       205  no
kafka-connect           active      1  kafka-connect  latest/edge   20  no

Unit              Workload  Agent  Machine  Public address  Ports           Message
active/0*         active    idle   0        10.86.75.171    19092/tcp
passive/0*        active    idle   1        10.86.75.153    9092,19092/tcp
kafka-connect/0*  active    idle   2        10.86.75.45     8083/tcp
```

As advised for active-passive replication, Kafka Connect should be integrated with the passive cluster. In this deployment it would be done by running the following command:

```bash
juju integrate kafka-connect passive
```

## Integrate MirrorMaker

To finish the deployment, we need to integrate the MirrorMaker charm with all three applications, both Kafka clusters and the Kafka Connect cluster.

Deploy mirrormaker:

```bash
juju deploy mirrormaker
```

After some time the app should show up in the model as blocked:

```bash
Unit              Workload  Agent  Machine  Public address  Ports           Message
mirrormaker/0*    blocked   idle   4        10.86.75.16                     Integrator not ready to start, check if all relations are setup successfully
```

The MirrorMaker application has two endpoints that can be used with a Kafka cluster: `source` and `target`. The `source` endpoint is used to integrate with the active cluster, while the `target` endpoint is used to integrate with the passive cluster.

```bash
juju integrate kafka-connect mirrormaker
juju integrate mirrormaker:source active
juju integrate mirrormaker:target passive
```

After some time, the app should show up in the model as active:

```bash
Model  Controller  Cloud/Region         Version  SLA          Timestamp
k      vms         localhost/localhost  3.6.3    unsupported  10:59:37+02:00

App            Version  Status  Scale  Charm          Channel      Rev  Exposed  Message
active         3.9.0    active      1  kafka          3/edge       205  no       
kafka-connect           active      1  kafka-connect  latest/edge   20  no       
mirrormaker             active      1  mirrormaker                   0  no       Task Status: UNASSIGNED
passive        3.9.0    active      1  kafka          3/edge       205  no       

Unit              Workload  Agent  Machine  Public address  Ports           Message
active/0*         active    idle   0        10.86.75.171    9092,19092/tcp  
kafka-connect/0*  active    idle   2        10.86.75.45     8083/tcp        
mirrormaker/0*    active    idle   3        10.86.75.189    8080/tcp        Task Status: UNASSIGNED
passive/0*        active    idle   1        10.86.75.153    9092,19092/tcp  
```

[note]
Task status might show as UNASSIGNED since there are no replication tasks running yet. If the active Kafka cluster is idle, this is expected. The task status will change to `RUNNING` once the replication tasks are created and started.
[\note]

With this, the deployment is complete. The MirrorMaker charm will now start replicating data from the active cluster to the passive cluster.


## Integrate active-active clusters.

MirrorMaker allows for a deployment where both clusters are active. This means that data can be replicated from both clusters to each other. This is done by creating a MirrorMaker connector for each cluster. Two flows are needed in this scenario, one from cluster A to cluster B and one from cluster B to cluster A.

In essence, it is equivalent to do two active-passive deployments, one on each direction. 

It is also recommended to have two Kafka Connect deployments ready, one on each end of the replication.

### Initial deployment

Two Mirrormaker integrators need to be deployed with the config option `prefix_topics` set to `true`. This will ensure that the topics are prefixed with the cluster name, so that they do not collide with each other.

```bash
juju deploy mirrormaker --config prefix_topics=true mirrormaker-a-b
juju deploy mirrormaker --config prefix_topics=true mirrormaker-b-a
```

A deployment with two clusters and active-active setup would be similar to this.

```bash
Model  Controller  Cloud/Region         Version  SLA          Timestamp
k      vms         localhost/localhost  3.6.3    unsupported  10:59:37+02:00

App              Version  Status  Scale  Charm          Channel      Rev  Exposed  Message
kafka-a          3.9.0    active      1  kafka          3/edge       205  no       
kafka-b          3.9.0    active      1  kafka          3/edge       205  no       
kafka-connect-a           active      1  kafka-connect  latest/edge   20  no       
kafka-connect-b           active      1  kafka-connect  latest/edge   20  no       
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

With this, the deployment is complete. There will be two replication flows from A to B and from B to A. The topics will be prefixed with the cluster name, so that they do not collide with each other. eg: a topic called `demo` in cluster A will be called `kafka-a.replica.demo` in cluster B, and a topic called `demo` in cluster B will be called `kafka-b.replica.demo` in cluster A.
