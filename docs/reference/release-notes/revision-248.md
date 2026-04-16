---
myst:
  html_meta:
    description: "Charmed Apache Kafka revision 248 release notes - Upgraded Apache Kafka to 4.1.0, Cruise Control, Karapace, Kafka Connect and Kafka UI stable releases, removed Apache ZooKeeper."
---

(reference-release-notes-revision-248)=
# Revision 248

Charmed Apache Kafka has been updated from Apache Kafka 3.9 to 4.1, bringing in the latest major-version changes. For more detail on the upstream changes, see the official Apache Kafka [4.0 release notes](https://archive.apache.org/dist/kafka/4.0.0/RELEASE_NOTES.html) and [4.1 release notes](https://archive.apache.org/dist/kafka/4.1.0/RELEASE_NOTES.html).

Apache ZooKeeper has now been fully removed as a dependency. For guidance on deploying Charmed Apache Kafka in production without ZooKeeper, see the [deployment documentation](https://documentation.ubuntu.com/charmed-kafka/4/how-to/deploy/#deploy-charmed-apache-kafka-for-production).

Cruise Control is now available as a stable feature for partition rebalancing. To learn how to rebalance partitions with Cruise Control, follow the [tutorial](https://documentation.ubuntu.com/charmed-kafka/4/tutorial/rebalance-partitions/).

Kafka Connect is also now generally available. You can find instructions for using Kafka Connect through the API in the [how-to guide](https://documentation.ubuntu.com/charmed-kafka/4/how-to/kafka-connect/).

MirrorMaker 2.0 Kafka Connect integrators have been released to `stable` as well, enabling cluster migration and replication workflows. See the [cluster documentation](https://documentation.ubuntu.com/charmed-kafka/4/how-to/cluster/) for guides on using MirrorMaker 2.0 with Kafka Connect.

Kafka Connect integrators are available for PostgreSQL, MySQL, S3, OpenSearch and MongoDB charms. For a hands-on example, see the [tutorial on using Kafka Connect Integrators](https://documentation.ubuntu.com/charmed-kafka/4/tutorial/use-kafka-connect/).

Karapace is now available as a stable, drop-in replacement for Schema Registry. For details on managing topic schemas with Karapace, refer to the [schemas and serialisation guide](https://documentation.ubuntu.com/charmed-kafka/4/how-to/schemas-serialisation/).

Kafka UI is now stable and can be used for cluster administration tasks. See the [Kafka UI documentation](https://documentation.ubuntu.com/charmed-kafka/4/how-to/kafka-ui/) for usage guidance.

OAuth support is now included, along with integration with Canonical Identity Platform. To enable OAuth, follow the [OAuth setup guide](https://documentation.ubuntu.com/charmed-kafka/4/how-to/oauth/).

[Charmhub](https://charmhub.io/kafka) | [Deploy guide](how-to-deploy-index) | [Upgrade instructions](how-to-upgrade) | [System requirements](reference-requirements)

```{warning}
This is a major release, and in-place upgrades of Charmed Apache Kafka applications across major versions are not supported.

See the documentation for how to migrate data between Charmed Apache Kafka clusters using [MirrorMaker](https://documentation.ubuntu.com/charmed-kafka/4/how-to/cluster/migrate/#how-to-cluster-migration).
```

## Features

- [DPE-7363](https://warthogs.atlassian.net/browse/DPE-7363) - feat: remove zookeeper & use Kafka 4 snap [#339](https://github.com/canonical/kafka-operator/pull/339)
- [DPE-7147](https://warthogs.atlassian.net/browse/DPE-7147) - feat: adapt mTLS support to DA150 spec [#344](https://github.com/canonical/kafka-operator/pull/344)
- [DPE-7142](https://warthogs.atlassian.net/browse/DPE-7142) - feat: update {spellexception}configs [#345](https://github.com/canonical/kafka-operator/pull/345)
- [DPE-7141](https://warthogs.atlassian.net/browse/DPE-7141) - feat: KRaft JBOD support [#349](https://github.com/canonical/kafka-operator/pull/349)
- [DPE-4428](https://warthogs.atlassian.net/browse/DPE-4428) - feat: Add `CONF`, `BIN`, `DATA`, `LOGS` {spellexception}env-vars to /etc/environment [#359](https://github.com/canonical/kafka-operator/pull/359)
- [DPE-7284](https://warthogs.atlassian.net/browse/DPE-7284) - feat: add support for secret-based user management [#360](https://github.com/canonical/kafka-operator/pull/360)
- [DPE-7413](https://warthogs.atlassian.net/browse/DPE-7413) - feat: extend SSL mapping validation [#354](https://github.com/canonical/kafka-operator/pull/354)
- [DPE-7657](https://warthogs.atlassian.net/browse/DPE-7657) - feat: add broker_active check [#375](https://github.com/canonical/kafka-operator/pull/375)
- [DPE-7526](https://warthogs.atlassian.net/browse/DPE-7526) - feat: use multiple TLS interfaces for internal/external [#353](https://github.com/canonical/kafka-operator/pull/353)
- [DPE-7522](https://warthogs.atlassian.net/browse/DPE-7522) - feat: add HA during CA rotation [#378](https://github.com/canonical/kafka-operator/pull/378)
- [DPE-7110](https://warthogs.atlassian.net/browse/DPE-7110) - feat: add support for Juju spaces [#385](https://github.com/canonical/kafka-operator/pull/385)
- [DPE-8031](https://warthogs.atlassian.net/browse/DPE-8031) - feat: add Terraform charm module [#408](https://github.com/canonical/kafka-operator/pull/408)
- [DPE-8312](https://warthogs.atlassian.net/browse/DPE-8312) - feat: auto-balance [#414](https://github.com/canonical/kafka-operator/pull/414)
- [DPE-9107](https://warthogs.atlassian.net/browse/DPE-9107) - feat: add machines support to {spellexception}TF module [#463](https://github.com/canonical/kafka-operator/pull/463)

## Improvements

- [DPE-7616](https://warthogs.atlassian.net/browse/DPE-7616) - {spellexception}cicd: add HA tests for controller [#371](https://github.com/canonical/kafka-operator/pull/371)
- [DPE-7150](https://warthogs.atlassian.net/browse/DPE-7150) - chore: refresh v3 [#380](https://github.com/canonical/kafka-operator/pull/380)
- [DPE-7138](https://warthogs.atlassian.net/browse/DPE-7138) - chore: switch to {spellexception}`kafka-python` [#401](https://github.com/canonical/kafka-operator/pull/401)
- [DPE-7583](https://warthogs.atlassian.net/browse/DPE-7583) - chore: split `metadata.log.dir` from `log.dirs` [#365](https://github.com/canonical/kafka-operator/pull/365)
- [DPE-7839](https://warthogs.atlassian.net/browse/DPE-7839) - chore: refactor `config-changed` [#409](https://github.com/canonical/kafka-operator/pull/409)
- [DPE-8311](https://warthogs.atlassian.net/browse/DPE-8311) - refactor: remove deployment mode logic from the TF module [#418](https://github.com/canonical/kafka-operator/pull/418)
- [DPE-8529](https://warthogs.atlassian.net/browse/DPE-8529) - feat: migrate to data_interfaces V1 [#423](https://github.com/canonical/kafka-operator/pull/423)
- [DPE-7790](https://warthogs.atlassian.net/browse/DPE-7790) - chore: rename internal users, use hyphen [#390](https://github.com/canonical/kafka-operator/pull/390)
- [DPE-9033](https://warthogs.atlassian.net/browse/DPE-9033) - chore: update TF provider to v1.0+ and TLS to 1/stable [#442](https://github.com/canonical/kafka-operator/pull/442)
- [DPE-8940](https://warthogs.atlassian.net/browse/DPE-8940) - chore: add OAuth integration tests and docs [#439](https://github.com/canonical/kafka-operator/pull/439)

## Bug fixes

- [DPE-5702](https://warthogs.atlassian.net/browse/DPE-5702) - chore: Active Controllers set to == 0 [#325](https://github.com/canonical/kafka-operator/pull/325)
- [DPE-6987](https://warthogs.atlassian.net/browse/DPE-6987) - fix: add readiness check for TLS handler [#335](https://github.com/canonical/kafka-operator/pull/335)
- [DPE-6436](https://warthogs.atlassian.net/browse/DPE-6436) - fix: use `pathops` for proper cleanup of TLS artefacts [#334](https://github.com/canonical/kafka-operator/pull/334)
- [DPE-7846](https://warthogs.atlassian.net/browse/DPE-7846) - fix: secrets not set issue in `RelationState` update [#387](https://github.com/canonical/kafka-operator/pull/387)
- [DPE-7987](https://warthogs.atlassian.net/browse/DPE-7987) - fix: race condition in internal TLS setup [#399](https://github.com/canonical/kafka-operator/pull/399)
- [DPE-4546](https://warthogs.atlassian.net/browse/DPE-4546) - fix: juju remove-unit app/leader breaks TLS [#400](https://github.com/canonical/kafka-operator/pull/400)

## Compatibility

Principal charms support the latest LTS series `24.04` only.

| Charm | Revision | Hardware architecture | Juju version | Artefacts |
|---|---|---|---|---|
| Charmed Apache Kafka | [248](https://github.com/canonical/kafka-operator/releases/tag/rev248) | AMD64 | Juju 3.6+ | Distribution: [4.1.1-ubuntu4](https://launchpad.net/kafka-releases/4.x/4.1.1-ubuntu4). <br> Snap: [revision 67](https://snapcraft.io/charmed-kafka). |
| Charmed Apache Kafka Connect | [33](https://github.com/canonical/kafka-connect-operator/releases/tag/rev33) | AMD64 | Juju 3.6+ | Distribution: [4.1.1-ubuntu4](https://launchpad.net/kafka-releases/4.x/4.1.1-ubuntu4). <br> Snap: [revision 48](https://snapcraft.io/charmed-kafka). |
| Charmed Karapace | [21](https://github.com/canonical/karapace-operator/releases/tag/rev21) | AMD64 | Juju 3.6+ | Snap: [revision 16](https://snapcraft.io/charmed-kafka). |
| Charmed Kafka UI | [6](https://github.com/canonical/kafka-ui-operator/releases/tag/rev6) | AMD64 | Juju 3.6+ | Snap: [revision 3](https://snapcraft.io/charmed-kafka-ui). |

Apache Kafka release notes: [4.0.0](https://archive.apache.org/dist/kafka/4.0.0/RELEASE_NOTES.html), [4.1.0](https://archive.apache.org/dist/kafka/4.1.0/RELEASE_NOTES.html).
