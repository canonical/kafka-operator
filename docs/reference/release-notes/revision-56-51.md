(reference-release-notes-revision-56-51)=
# Revision 56/51
<sub>Wednesday, February 28, 2024</sub>

Charmed Apache Kafka K8s and Charmed Apache ZooKeeper K8s have been released for General Availability.

[Charmhub](https://charmhub.io/kafka-k8s) | [Deploy guide](how-to-deploy-index) | [Upgrade instructions](how-to-upgrade) | [System requirements](reference-requirements)

## Features

* Deploying on Kubernetes (tested with MicroK8s)
* Apache ZooKeeper using SASL authentication
* Scaling up/down in one simple Juju command
* Multi-broker support and Highly-Available setups
* Inter-broker authenticated communication
* TLS/SSL support using `tls-certificates` Provider charms ([see more](https://charmhub.io/topics/security-with-x-509-certificates))
* SASL/SCRAM and mTLS authentication for clients
* DB access outside of Juju using [`data-integrator`](https://charmhub.io/data-integrator)
* Persistent storage support with Juju Storage
* Super-user creation
* Documentation featuring Diàtaxis framework

## Other improvements

* Canonical Data issues are now public on both [Jira](https://warthogs.atlassian.net/jira/software/c/projects/DPE/issues/) 
and [GitHub](https://github.com/canonical/kafka-k8s-operator/issues) platforms.
* [GitHub Releases](https://github.com/canonical/kafka-k8s-operator/releases) provide a detailed list of bug fixes, PRs, and commits for each revision.

## Compatibility

Principal charms support the latest LTS series “22.04” only.

| Charm | Revision | Hardware architecture | Juju version | Artefacts |
|---|---|---|---|---|
| Charmed Apache Kafka K8s | [56](https://github.com/canonical/kafka-k8s-operator/tree/rev56) | AMD64 | 2.9.45+, Juju 3.1+ | Distribution: [3.6.0-ubuntu0](https://launchpad.net/kafka-releases/3.x/3.6.0-ubuntu0). <br> `charmed-kafka` rock: [{spellexception}`sha256:4b3495`](https://github.com/canonical/charmed-kafka-rock/pkgs/container/charmed-kafka/169796414). |
| Charmed Apache ZooKeeper K8s | [51](https://github.com/canonical/zookeeper-k8s-operator/tree/rev51) | AMD64 | 2.9.45+, Juju 3.1+ | Distribution: [3.8.2-ubuntu0](https://launchpad.net/zookeeper-releases/3.x/3.8.2-ubuntu0). <br> `charmed-zookeeper` rock: [{spellexception}`sha256:a7a004`](https://github.com/canonical/charmed-zookeeper-rock/pkgs/container/charmed-zookeeper/169796097). |

## Known issues

* Revision 126 of Charmed Apache ZooKeeper was observed to sporadically trigger Apache ZooKeeper reconfiguration of the clusters by removing all servers but the Juju leader from the Apache ZooKeeper quorum.
This leads to a non-highly available cluster, that it is however still up and running.
  * Recommendation: Upgrade to a newer version: revision 136+.
* The current version of Apache Kafka does not yet support direct integration with Ingress, NodePort or Load Balancer services.
  * Recommendation: We recommend using it within the K8s network.
