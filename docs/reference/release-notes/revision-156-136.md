(reference-release-notes-revision-156-136)=
# Revision 156/136
<sub>Thursday, July 4, 2024</sub>

Charmed Apache ZooKeeper upgraded to revision 136 to fix bugs, increase robustness and resilience during operation, as well as upgrade its workload.

[Charmhub](https://charmhub.io/kafka) | [Deploy guide](how-to-deploy-index) | [Upgrade instructions](how-to-upgrade) | [System requirements](reference-requirements)

## Bug fixes

* [[DPE-4183](https://warthogs.atlassian.net/browse/DPE-4183)] (backport) fix: only handle quorum removal on relation-departed.
  * Provides more robust logic to avoid dynamic reconfiguration in case of Juju connection problems.  
* [[DPE-4362](https://warthogs.atlassian.net/browse/DPE-4362)] (backport) add alive check fix.

## Other improvements

* [[DPE-3726](https://warthogs.atlassian.net/browse/DPE-3726)] Apache ZooKeeper upgrade to `3.8.4-ubuntu0`.

## Compatibility

Principal charms support the latest LTS series “22.04” only.

| Charm | Revision | Hardware architecture | Juju version | Artefacts |
|---|---|---|---|---|
| Charmed Apache Kafka | [156](https://github.com/canonical/kafka-operator/tree/01d65c3444b593d5f18d197a6514421afd3f2bc6) | AMD64 | 2.9.45+, Juju 3.1+ | Distribution: [3.6.0-ubuntu0](https://launchpad.net/kafka-releases/3.x/3.6.0-ubuntu0). <br> Snap: [revision 30](https://snapcraft.io/charmed-kafka). |
| Charmed Apache ZooKeeper | [136](https://github.com/canonical/zookeeper-operator/tree/0b7d66170d80e23804032034119a419f174bb965) | AMD64 | 2.9.45+, Juju 3.1+ | Distribution: [3.8.4-ubuntu0](https://launchpad.net/zookeeper-releases/3.x/3.8.4-ubuntu0). <br> Snap: [revision 30](https://snapcraft.io/charmed-zookeeper). |
