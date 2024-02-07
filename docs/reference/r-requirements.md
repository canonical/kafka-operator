## Juju version

The charm supports both [Juju 2.9 LTS](https://github.com/juju/juju/releases) and [Juju 3.1](https://github.com/juju/juju/releases). However, we always advise new deployment to be carried out on Juju 3. 

The minimum supported Juju versions are:

* 2.9.32+ (no tests made for older versions).
* 3.1.6+ (due to issues with Juju secrets in previous versions, see [#1](https://bugs.launchpad.net/juju/+bug/2029285) and [#2](https://bugs.launchpad.net/juju/+bug/2029282))

## Minimum requirements

For production environments, it is recommended to deploy at least 5 nodes for Zookeeper and 3 for Kafka. While the following requirements are meant to be for production, the charm can be deployed in much smaller environments.

- 64GB of RAM
- 24 cores
- 12 storage devices
- 10 GbE card

## Supported architectures

The charm is based on SNAP "[charmed-kafkal](https://snapcraft.io/charmed-kafka)", which is currently available for `amd64` only! The architecture `arm64` support is planned. Please [contact us](/t/13107) if you are interested in new architecture!