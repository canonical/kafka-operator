---
myst:
  html_meta:
    description: "Charmed Apache Kafka revision 248 release notes - Apache Kafka 4.1.0, Apache ZooKeeper removed, Cruise Control, Karapace, Kafka Connect and Kafka UI stable releases."
---

(reference-release-notes-revision-248)=
# Revision 248

## Charmed Apache Kafka

New revisions of [Charmed Apache Kafka](http://charmhub.io/kafka) and [Charmed Apache Kafka K8s](http://charmhub.io/kafka-k8s) have been published to their `4/stable` channels.

```{warning}
This is a Major version release and in-place upgrades are NOT supported from Charmed Kafka applications on the `3/stable` channel.

Check the documentation on how to migrate data between Charmed Apache Kafka clusters using [MirrorMaker](https://documentation.ubuntu.com/charmed-kafka/4/how-to/cluster/migrate/#how-to-cluster-migration)
```

New revisions of [Charmed Apache Kafka Connect](http://charmhub.io/kafka-connect) and [Charmed Apache Kafka Connect K8s](http://charmhub.io/kafka-connect-k8s) have been published to their `4/stable` channels.

New revisions of [Karapace](http://charmhub.io/karapace) and [Karapace K8s](http://charmhub.io/karapace-k8s) have been published to their `4/stable` channels.

New revisions of [Kafka UI](http://charmhub.io/kafka-ui) and [Kafka UI K8s](http://charmhub.io/kafka-ui) have been published to their `4/stable` channels.

### Highlights

- **New major version release of Apache Kafka version from 3.9 -> 4.1**
    - Check the official Apache Kafka [Version 4.0 release notes](https://downloads.apache.org/kafka/4.0.0/RELEASE_NOTES.html)
    - Check the official Apache Kafka [Version 4.1 release notes](https://downloads.apache.org/kafka/4.1.0/RELEASE_NOTES.html)
- **Apache ZooKeeper fully removed as a dependency**
    - Check the [documentation](https://documentation.ubuntu.com/charmed-kafka/4/how-to/deploy/#deploy-charmed-apache-kafka-for-production) for a guide on how to deploy for production
- **Stable release of Cruise Control for partition rebalancing**
    - Check the [documentation](https://documentation.ubuntu.com/charmed-kafka/4/tutorial/rebalance-partitions/) for a tutorial on rebalancing partitions using Cruise Control
- **Stable release of Kafka Connect**
    - Check the [documentation](https://documentation.ubuntu.com/charmed-kafka/4/how-to/kafka-connect/) for a guide on using Kafka Connect via the API
- **Stable release of MirrorMaker2.0 Connect integrators**
    - Check the [documentation](https://documentation.ubuntu.com/charmed-kafka/4/how-to/cluster/) for guides on cluster migration and replication using MirrorMaker2.0 with Kafka Connect
- **Kafka Connect integrators for PostgreSQL, MySQL, S3, OpenSearch and MongoDB charms**
    - Check the [documentation](https://documentation.ubuntu.com/charmed-kafka/4/tutorial/use-kafka-connect/) for a tutorial on using Kafka Connect integrators
- **Stable release of Karapace as a drop-in replacement for Schema Registry**
    - Check the [documentation](https://documentation.ubuntu.com/charmed-kafka/4/how-to/schemas-serialisation/) for a guide on managing topic schemas using Karapace
- **Stable release of Kafka UI**
    - Check the [documentation](https://documentation.ubuntu.com/charmed-kafka/4/how-to/kafka-ui/) for a guide on using the Kafka UI for cluster administration
- **OAuth support and Canonical Identity Platform integration**
    - Check the [documentation](https://documentation.ubuntu.com/charmed-kafka/4/how-to/oauth/) for a guide on enabling OAuth with Canonical Identity platform

### Features

- [DPE-7363](https://warthogs.atlassian.net/browse/DPE-7363) - feat: remove zookeeper & use Kafka 4 snap [#339](https://github.com/canonical/kafka-operator/pull/339)
- [DPE-7147](https://warthogs.atlassian.net/browse/DPE-7147) - feat: adapt MTLS support to DA150 spec [#344](https://github.com/canonical/kafka-operator/pull/344)
- [DPE-7142](https://warthogs.atlassian.net/browse/DPE-7142) - feat: update configs [#345](https://github.com/canonical/kafka-operator/pull/345)
- [DPE-7141](https://warthogs.atlassian.net/browse/DPE-7141) - feat: KRaft JBOD support [#349](https://github.com/canonical/kafka-operator/pull/349)
- [DPE-4428](https://warthogs.atlassian.net/browse/DPE-4428) - feat: Add CONF, BIN, DATA, LOGS env-vars to /etc/environment [#359](https://github.com/canonical/kafka-operator/pull/359)
- [DPE-7284](https://warthogs.atlassian.net/browse/DPE-7284) - feat: add support for secret-based user management [#360](https://github.com/canonical/kafka-operator/pull/360)
- [DPE-7413](https://warthogs.atlassian.net/browse/DPE-7413) - feat: extend SSL mapping validation [#354](https://github.com/canonical/kafka-operator/pull/354)
- [DPE-7657](https://warthogs.atlassian.net/browse/DPE-7657) - feat: add broker_active check [#375](https://github.com/canonical/kafka-operator/pull/375)
- [DPE-7526](https://warthogs.atlassian.net/browse/DPE-7526) - feat: use multiple TLS interfaces for internal/external [#353](https://github.com/canonical/kafka-operator/pull/353)
- [DPE-7522](https://warthogs.atlassian.net/browse/DPE-7522) - feat: add HA during CA rotation [#378](https://github.com/canonical/kafka-operator/pull/378)
- [DPE-7110](https://warthogs.atlassian.net/browse/DPE-7110) - feat: add support for Juju spaces [#385](https://github.com/canonical/kafka-operator/pull/385)
- [DPE-8031](https://warthogs.atlassian.net/browse/DPE-8031) - feat: add Terraform charm module [#408](https://github.com/canonical/kafka-operator/pull/408)
- [DPE-8312](https://warthogs.atlassian.net/browse/DPE-8312) - feat: auto-balance [#414](https://github.com/canonical/kafka-operator/pull/414)
- [DPE-9107](https://warthogs.atlassian.net/browse/DPE-9107) - feat: add machines support to TF module [#463](https://github.com/canonical/kafka-operator/pull/463)

### Improvements

- [DPE-7616](https://warthogs.atlassian.net/browse/DPE-7616) - ci: add HA tests for controller [#371](https://github.com/canonical/kafka-operator/pull/371)
- [DPE-7150](https://warthogs.atlassian.net/browse/DPE-7150) - chore: refresh v3 [#380](https://github.com/canonical/kafka-operator/pull/380)
- [DPE-7138](https://warthogs.atlassian.net/browse/DPE-7138) - chore: switch to kafka-python [#401](https://github.com/canonical/kafka-operator/pull/401)
- [DPE-7583](https://warthogs.atlassian.net/browse/DPE-7583) - chore: split metadata.log.dir from log.dirs [#365](https://github.com/canonical/kafka-operator/pull/365)
- [DPE-7839](https://warthogs.atlassian.net/browse/DPE-7839) - chore: refactor config changed [#409](https://github.com/canonical/kafka-operator/pull/409)
- [DPE-8311](https://warthogs.atlassian.net/browse/DPE-8311) - refactor: remove deployment mode logic from the TF module [#418](https://github.com/canonical/kafka-operator/pull/418)
- [DPE-8529](https://warthogs.atlassian.net/browse/DPE-8529) - feat: migrate to data_interfaces V1 [#423](https://github.com/canonical/kafka-operator/pull/423)
- [DPE-7790](https://warthogs.atlassian.net/browse/DPE-7790) - chore: rename internal users, use hyphen [#390](https://github.com/canonical/kafka-operator/pull/390)
- [DPE-9033](https://warthogs.atlassian.net/browse/DPE-9033) - chore: update TF provider to v1.0+ and TLS to 1/stable [#442](https://github.com/canonical/kafka-operator/pull/442)
- [DPE-8940](https://warthogs.atlassian.net/browse/DPE-8940) - chore: add OAuth integration tests and docs [#439](https://github.com/canonical/kafka-operator/pull/439)

### Bug fixes

- [DPE-5702](https://warthogs.atlassian.net/browse/DPE-5702) - chore: Active Controllers set to == 0 [#325](https://github.com/canonical/kafka-operator/pull/325)
- [DPE-6987](https://warthogs.atlassian.net/browse/DPE-6987) - fix: add readiness check for TLS handler [#335](https://github.com/canonical/kafka-operator/pull/335)
- [DPE-6436](https://warthogs.atlassian.net/browse/DPE-6436) - fix: use pathops for proper cleanup of TLS artifacts [#334](https://github.com/canonical/kafka-operator/pull/334)
- [DPE-7846](https://warthogs.atlassian.net/browse/DPE-7846) - fix: secrets not set issue in RelationState.update [#387](https://github.com/canonical/kafka-operator/pull/387)
- [DPE-7987](https://warthogs.atlassian.net/browse/DPE-7987) - fix: race condition in internal TLS setup [#399](https://github.com/canonical/kafka-operator/pull/399)
- [DPE-4546](https://warthogs.atlassian.net/browse/DPE-4546) - fix: juju remove-unit app/leader breaks TLS [#400](https://github.com/canonical/kafka-operator/pull/400)
