---
myst:
  html_meta:
    description: "Kubernetes revision 56/51 release notes for Charmed Apache Kafka and ZooKeeper."
---

(reference-release-notes-k8s-revision-56-51)=
(reference-release-notes-revision-56-51)=
# Revision 56/51
<sub>Wednesday, February 28, 2024</sub>

Charmed Apache Kafka K8s and Charmed Apache ZooKeeper K8s were released for
General Availability.

[Kafka K8s on Charmhub](https://charmhub.io/kafka-k8s) |
[Deploy guide](how-to-deploy-index) |
[Upgrade instructions](how-to-upgrade) |
[System requirements](reference-requirements)

## Features

* Deployment on Kubernetes (tested with MicroK8s)
* Apache ZooKeeper using SASL authentication
* Scaling up or down in one Juju command
* Multi-broker and highly available deployments
* Authenticated inter-broker communication
* TLS/SSL through `tls-certificates` provider charms
* SASL/SCRAM and mTLS client authentication
* External client credentials through [`data-integrator`](https://charmhub.io/data-integrator)
* Persistent storage through Juju storage
* Super-user creation

## Compatibility at release time

Principal charms supported Ubuntu 22.04 LTS.

| Charm | Revision | Architecture | Juju | Artefacts |
|---|---:|---|---|---|
| Charmed Apache Kafka K8s | [56](https://github.com/canonical/kafka-k8s-operator/tree/rev56) | AMD64 | 2.9.45+, 3.1+ | [Kafka 3.6.0-ubuntu0](https://launchpad.net/kafka-releases/3.x/3.6.0-ubuntu0); `charmed-kafka` rock `sha256:4b3495` |
| Charmed Apache ZooKeeper K8s | [51](https://github.com/canonical/zookeeper-k8s-operator/tree/rev51) | AMD64 | 2.9.45+, 3.1+ | [ZooKeeper 3.8.2-ubuntu0](https://launchpad.net/zookeeper-releases/3.x/3.8.2-ubuntu0); `charmed-zookeeper` rock `sha256:a7a004` |

## Known issues at release time

* ZooKeeper revision 126 could sporadically remove all servers except the Juju
  leader from the quorum. The recommendation was to upgrade ZooKeeper to
  revision 136 or later.
* Direct Ingress, NodePort, and LoadBalancer integration was not available in
  this release. Current 4.x K8s releases support NodePort; see [External K8s
  connection](how-to-external-k8s-connection).
