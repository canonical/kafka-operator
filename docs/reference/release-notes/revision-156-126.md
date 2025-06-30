(reference-release-notes-revision-156-126)=
# Revision 156/126
<sub>Wednesday, February 28, 2024</sub>

Charmed Apache Kafka and Charmed Apache ZooKeeper have been released for General Availability.

[Charmhub](https://charmhub.io/kafka) | [Deploy guide](how-to-deploy-index) | [Upgrade instructions](how-to-upgrade) | [System requirements](reference-requirements)

## Features

* Deploying on VM (tested with LXD, MAAS)
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
and [GitHub](https://github.com/canonical/kafka-operator/issues) platforms.
* [GitHub Releases](https://github.com/canonical/kafka-operator/releases) provide a detailed list of bug fixes, PRs, and commits for each revision.

## Compatibility

Principal charms support the latest LTS series “22.04” only.

| Charm | Revision | Hardware architecture | Juju version | Artefacts |
|---|---|---|---|---|
| Charmed Apache Kafka | [156](https://github.com/canonical/kafka-operator/tree/01d65c3444b593d5f18d197a6514421afd3f2bc6) | AMD64 | 2.9.45+, Juju 3.1+ | Distribution: [3.6.0-ubuntu0](https://launchpad.net/kafka-releases/3.x/3.6.0-ubuntu0). <br> Snap: [revision 30](https://snapcraft.io/charmed-kafka). |
| Charmed Apache ZooKeeper | [126](https://github.com/canonical/zookeeper-operator/tree/9ebd9a2050e0bd626feb0019222d45f211ca7774) | AMD64 | 2.9.45+, Juju 3.1+ | Distribution: [3.8.2-ubuntu0](https://launchpad.net/zookeeper-releases/3.x/3.8.2-ubuntu0). <br> Snap: [revision 28](https://snapcraft.io/charmed-zookeeper). |

## Known issues

* Revision 126 of Charmed Apache ZooKeeper was observed to sporadically trigger Apache ZooKeeper reconfiguration of the clusters by removing all servers but the Juju leader from the Apache ZooKeeper quorum.
This leads to a non-highly available cluster, that it is however still up and running.
  * Recommendation: Upgrade to a newer version: revision 136+.
