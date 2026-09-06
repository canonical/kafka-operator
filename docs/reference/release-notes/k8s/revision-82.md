---
myst:
  html_meta:
    description: "Kubernetes revision 82 release notes with Kafka 3.9, KRaft, Cruise Control, and Karapace support."
---

(reference-release-notes-k8s-revision-82)=
(reference-release-notes-release-82)=
# Revision 82

This release upgraded Apache Kafka to `3.9.0` and Apache ZooKeeper to `3.9.2`,
and added support for Cruise Control partition rebalancing, KRaft, Karapace, and
backup and restore through S3.

[Kafka K8s on Charmhub](https://charmhub.io/kafka-k8s) |
[Deploy guide](how-to-deploy-index) |
[Upgrade instructions](how-to-upgrade) |
[System requirements](reference-requirements)

## Charmed Apache Kafka K8s

### Features

* Cruise Control partition rebalancing ([DPE-2872](https://warthogs.atlassian.net/browse/DPE-2872))
* KRaft consensus protocol ([DPE-4328](https://warthogs.atlassian.net/browse/DPE-4328))
* Cross-model K8s relations with `juju expose` ([DPE-6574](https://warthogs.atlassian.net/browse/DPE-6574))
* Multi-certificate CA chains ([DPE-6260](https://warthogs.atlassian.net/browse/DPE-6260))
* Non-unit and non-port extra listeners ([DPE-6636](https://warthogs.atlassian.net/browse/DPE-6636))

### Improvements and fixes

This release reworked status handling and the central broker relation, improved
KRaft scaling, secured ZooKeeper data, restored prefixed topic names, removed
`lost+found` from new storage, improved certificate SAN handling, and stabilised
integration tests. See the [GitHub release history](https://github.com/canonical/kafka-k8s-operator/releases)
for the complete change list.

## Charmed Apache ZooKeeper K8s

This release added S3 integration, external exposure, digest authentication, TLS
certificate chains, backup and restore actions, TLS 1.2 client communication,
and several reconfiguration and relation cleanup fixes.

## Compatibility at release time

Principal charms supported Ubuntu 22.04 LTS.

| Charm | Revision | Architecture | Juju | Artefacts |
|---|---:|---|---|---|
| Charmed Apache Kafka K8s | [82](https://github.com/canonical/kafka-k8s-operator/tree/rev82) | AMD64 | 2.9.45+, 3.1+ | [Kafka 3.9.0-ubuntu1](https://launchpad.net/kafka-releases/3.x/3.9.0-ubuntu1); `charmed-kafka` rock `sha256:fa919f` |
| Charmed Apache ZooKeeper K8s | [51](https://github.com/canonical/zookeeper-k8s-operator/tree/rev51) | AMD64 | 2.9.45+, 3.1+ | [ZooKeeper 3.8.2-ubuntu0](https://launchpad.net/zookeeper-releases/3.x/3.8.2-ubuntu0); `charmed-zookeeper` rock `sha256:a7a004` |

Apache Kafka release notes: [3.7.0](https://archive.apache.org/dist/kafka/3.7.0/RELEASE_NOTES.html),
[3.8.0](https://archive.apache.org/dist/kafka/3.8.0/RELEASE_NOTES.html), and
[3.9.0](https://archive.apache.org/dist/kafka/3.9.0/RELEASE_NOTES.html).
