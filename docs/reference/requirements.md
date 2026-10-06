(reference-requirements)=
# Requirements

## Juju version

The charm currently runs both on [Juju 2.9 LTS](https://github.com/juju/juju/releases) and [Juju 3.1](https://github.com/juju/juju/releases), although 2.9 is now deprecated and support on this Juju version may be discontinued in future charm release. We therefore advise new deployments to be carried out on Juju 3.

For migration of the deployment from a Juju 2.9 to a 3.x controller, please [get in touch](reference-contact) with the product team.

The minimum supported Juju versions are:

- 2.9.32+ (although deprecated)
- 3.1.6+ (due to issues with Juju secrets in previous versions, see [#1](https://bugs.launchpad.net/juju/+bug/2029285) and [#2](https://bugs.launchpad.net/juju/+bug/2029282))

## Minimum requirements

For production environments, it is recommended to deploy at least five nodes for Apache ZooKeeper and three for Apache Kafka. While the following requirements are meant to be for production, the charm can be deployed in much smaller environments.

- 64GB of RAM
- 24 cores
- At least 50GB of available storage
- Access to the internet for downloading the required OCI/ROCKs and charms.

## Supported architectures

The charm is based on [ROCK OCI](https://github.com/canonical/charmed-kafka-rock) named "[{spellexception}`charmed-kafka`](https://github.com/canonical/charmed-kafka-rock/pkgs/container/charmed-kafka)", which is recursively based on SNAP "[{spellexception}`charmed-kafka`](https://snapcraft.io/charmed-kafka)", which is currently available for `amd64` only! The architecture `arm64` support is planned. Please [contact us](reference-contact) if you are interested in new architectures!
