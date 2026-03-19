(reference-release-notes-revision-195-149)=
# Revision 195/149
<sub>Wed, Dec 18th, 2024</sub>

This release comes with a number of new features for the charms, Juju secrets support, OAuth/OIDC authentication support, various improvements in the UI/UX, and dependencies upgrades.  

[Charmhub](https://charmhub.io/kafka) | [Deploy guide](how-to-deploy-index) | [Upgrade instructions](how-to-upgrade) | [System requirements](reference-requirements)

## Charmed Apache Kafka

New features and bug fixes in the Charmed Apache Kafka bundle:

### Features

* [[DPE-2285](https://warthogs.atlassian.net/browse/DPE-2285)] Refer to Charmhub space from GitHub ([#200](https://github.com/canonical/kafka-operator/pull/200))
* [[DPE-3333](https://warthogs.atlassian.net/browse/DPE-3333)] Add integration test for broken tls ([#188](https://github.com/canonical/kafka-operator/pull/188))
* [[DPE-3721](https://warthogs.atlassian.net/browse/DPE-3721)] chore: use tools-log4j.properties for run_bin_command ([#201](https://github.com/canonical/kafka-operator/pull/201))
* [[DPE-3735](https://warthogs.atlassian.net/browse/DPE-3735)] Integration of custom alerting rules and dashboards ([#180](https://github.com/canonical/kafka-operator/pull/180))
* [[DPE-3780](https://warthogs.atlassian.net/browse/DPE-3780)] Set workload version in install hook ([#182](https://github.com/canonical/kafka-operator/pull/182))
* [[DPE-3857](https://warthogs.atlassian.net/browse/DPE-3857)] Test consistency between workload and metadata versions ([#186](https://github.com/canonical/kafka-operator/pull/186))
* [[DPE-3926](https://warthogs.atlassian.net/browse/DPE-3926)] Enforce zookeeper client interface ([#196](https://github.com/canonical/kafka-operator/pull/196))
* [[DPE-3928](https://warthogs.atlassian.net/browse/DPE-3928)] feat: secrets integration ([#189](https://github.com/canonical/kafka-operator/pull/189))
* [[DPE-5702](https://warthogs.atlassian.net/browse/DPE-5702)] chore: Active Controllers alert set to == 0 ([#252](https://github.com/canonical/kafka-operator/pull/252))
* [[CSS-6503](https://warthogs.atlassian.net/browse/CSS-6503)] Add OAuth support for non-charmed external clients ([#168](https://github.com/canonical/kafka-operator/pull/168))
* [[DPE-5757](https://warthogs.atlassian.net/browse/DPE-5757)] Add `extra-listeners` configuration option ([#269](https://github.com/canonical/kafka-operator/pull/269))

### Bug fixes

* [[DPE-3880](https://warthogs.atlassian.net/browse/DPE-3880)] Remove instance field from Grafana dashboard ([#191](https://github.com/canonical/kafka-operator/pull/191)) 
* [[DPE-3880](https://warthogs.atlassian.net/browse/DPE-3880)] Remove all instances of $job variable in dashboard ([#181](https://github.com/canonical/kafka-operator/pull/181))
* [[DPE-3900](https://warthogs.atlassian.net/browse/DPE-3900)] Remove APT references ([#183](https://github.com/canonical/kafka-operator/pull/183))
* [[DPE-3932](https://warthogs.atlassian.net/browse/DPE-3932)] Fix unsupported character on matrix channel ([#187](https://github.com/canonical/kafka-operator/pull/187))
* [[DPE-4133](https://warthogs.atlassian.net/browse/DPE-4133)] Do not change permissions on existing folders when reusing storage ([#195](https://github.com/canonical/kafka-operator/pull/195))
* [[DPE-4362](https://warthogs.atlassian.net/browse/DPE-4362)] fix: alive, restart and alive handling ([#202](https://github.com/canonical/kafka-operator/pull/202))
* [[DPE-5757](https://warthogs.atlassian.net/browse/DPE-5757)] fix: ensure certs are refreshed on SANs DNS changes ([#276](https://github.com/canonical/kafka-operator/pull/276))

### Other improvements

* [MISC] Test on Juju 3.4 ([#190](https://github.com/canonical/kafka-operator/pull/190))
* [MISC] Update package dependencies
* [[DPE-3588](https://warthogs.atlassian.net/browse/DPE-3588)] Release documentation update  ([#175](https://github.com/canonical/kafka-operator/pull/175))
* [MISC] CI improvements ([#209](https://github.com/canonical/kafka-operator/pull/209))
* [[DPE-3214](https://warthogs.atlassian.net/browse/DPE-3214)] Release 3.6.1 ([#179](https://github.com/canonical/kafka-operator/pull/179))
* [[DPE-5565](https://warthogs.atlassian.net/browse/DPE-5565)] Upgrade data platform libs to v38
* [discourse-gatekeeper] Migrate charm docs ([#210](https://github.com/canonical/kafka-operator/pull/210), [#203](https://github.com/canonical/kafka-operator/pull/203), [#198](https://github.com/canonical/kafka-operator/pull/198), [#194](https://github.com/canonical/kafka-operator/pull/194), [#192](https://github.com/canonical/kafka-operator/pull/192))
* [[DPE-3932](https://warthogs.atlassian.net/browse/DPE-3932)] Update information in metadata.yaml

## Charmed Apache ZooKeeper

New features and bug fixes in the Charmed Apache ZooKeeper bundle:

### Features

* [[DPE-2285](https://warthogs.atlassian.net/browse/DPE-2285)] Refer to Charmhub space from GitHub ([#143](https://github.com/canonical/zookeeper-operator/pull/143))
* [[DPE-2597](https://warthogs.atlassian.net/browse/DPE-2597)] Re use existing storage ([#138](https://github.com/canonical/zookeeper-operator/pull/138))
* [[DPE-3737](https://warthogs.atlassian.net/browse/DPE-3737)] Implement ZK client interface ([#142](https://github.com/canonical/zookeeper-operator/pull/142))
* [[DPE-3782](https://warthogs.atlassian.net/browse/DPE-3782)] Set workload version in install and configure hooks ([#130](https://github.com/canonical/zookeeper-operator/pull/130))
* [[DPE-3857](https://warthogs.atlassian.net/browse/DPE-3857)] Test consistency between workload and metadata versions ([#136](https://github.com/canonical/zookeeper-operator/pull/136))
* [[DPE-3869](https://warthogs.atlassian.net/browse/DPE-3869)] Secrets in ZK ([#129](https://github.com/canonical/zookeeper-operator/pull/129))
* [[DPE-5626](https://warthogs.atlassian.net/browse/DPE-5626)] chore: update ZooKeeper up alerting ([#166](https://github.com/canonical/zookeeper-operator/pull/166))

### Bug fixes

* [[DPE-3880](https://warthogs.atlassian.net/browse/DPE-3880)] Remove job variable from dashboard ([#134](https://github.com/canonical/zookeeper-operator/pull/134))
* [[DPE-3900](https://warthogs.atlassian.net/browse/DPE-3900)] Remove APT references ([#131](https://github.com/canonical/zookeeper-operator/pull/131))
* [[DPE-3932](https://warthogs.atlassian.net/browse/DPE-3932)] Fix unsupported character on matrix channel ([#133](https://github.com/canonical/zookeeper-operator/pull/133), [#135](https://github.com/canonical/zookeeper-operator/pull/135))
* [[DPE-4183](https://warthogs.atlassian.net/browse/DPE-4183)] fix: only handle quorum removal on relation-departed ([#146](https://github.com/canonical/zookeeper-operator/pull/146))
* [[DPE-4362](https://warthogs.atlassian.net/browse/DPE-4362)] fix: alive, restart and alive handling ([#145](https://github.com/canonical/zookeeper-operator/pull/145))

### Other improvements

* [[DPE-5565](https://warthogs.atlassian.net/browse/DPE-5565)] Stable release upgrade
* chore: bump {spellexception}`dp_libs` version ([#147](https://github.com/canonical/zookeeper-operator/pull/147))
* [MISC] General update dependencies ([#144](https://github.com/canonical/zookeeper-operator/pull/144))
* [MISC] Update CI to Juju 3.4 ([#137](https://github.com/canonical/zookeeper-operator/pull/137))
* [[DPE-3932](https://warthogs.atlassian.net/browse/DPE-3932)] Update information in metadata.yaml
* [MISC] Update cryptography to 42.0.5

## Compatibility

Principal charms support the latest LTS series “22.04” only.

| Charm | Revision | Hardware architecture | Juju version | Artefacts |
|---|---|---|---|---|
| Charmed Apache Kafka | [195](https://github.com/canonical/kafka-operator/tree/7948dfbbfaaa53fccc88beaa90f80de1e70beaa9) | AMD64 | 2.9.45+, Juju 3.1+ | Distribution: [3.6.1-ubuntu0](https://launchpad.net/kafka-releases/3.x/3.6.1-ubuntu0). <br> Snap: [revision 37](https://snapcraft.io/charmed-kafka). |
| Charmed Apache ZooKeeper | [149](https://github.com/canonical/zookeeper-operator/tree/40576c1c87badd1e2352afc013ed0754808ef44c) | AMD64 | 2.9.45+, Juju 3.1+ | Distribution: [3.8.4-ubuntu0](https://launchpad.net/zookeeper-releases/3.x/3.8.4-ubuntu0). <br> Snap: [revision 34](https://snapcraft.io/charmed-zookeeper). |
