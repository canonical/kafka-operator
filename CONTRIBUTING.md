# Contributing

## Overview

This documents explains the processes and practices recommended for contributing enhancements to this operator.

- Generally, before developing enhancements to this charm, you should consider [opening an issue](https://github.com/canonical/kafka-operator/issues) explaining your problem with examples, and your desired use case.
- If you would like to chat with us about your use-cases or proposed implementation, you can reach us at [Canonical Mattermost public channel](https://chat.charmhub.io/charmhub/channels/charm-dev) or [Discourse](https://discourse.charmhub.io/).
- Familiarising yourself with the [Charmed Operator Framework](https://juju.is/docs/sdk) library will help you a lot when working on new features or bug fixes.
- All enhancements require review before being merged. Code review typically examines
  - code quality
  - test coverage
  - user experience for Juju administrators this charm.
- Please help us out in ensuring easy to review branches by rebasing your pull request branch onto the `main` branch. This also avoids merge commits and creates a linear Git commit history.

## Requirements

To build the charm locally, you will need to install [Charmcraft](https://juju.is/docs/sdk/install-charmcraft).

To run the charm locally with Juju, it is recommended to use [LXD](https://linuxcontainers.org/lxd/introduction/) as your virtual machine manager. Instructions for running Juju on LXD can be found [here](https://juju.is/docs/olm/lxd).

## Build and Deploy

To build the charm in this repository, from the root of the dir you can run:
Once you have Juju set up locally, to download, build and deploy the charm you can run:

### Deploy

```bash
# Clone and enter the repository
git clone https://github.com/canonical/kafka-operator.git
cd kafka-operator/

# Create a working model
juju add-model kafka

# Enable DEBUG logging for the model
juju model-config logging-config="<root>=INFO;unit=DEBUG"

# Build the charm locally
charmcraft pack

# Deploy the latest ZooKeeper release
juju deploy zookeeper --channel edge -n 3

# Deploy the charm
juju deploy ./*.charm -n 3

# After ZooKeeper has initialised, relate the applications
juju relate kafka zookeeper
```

## Developing

You can create an environment for development with `tox`:

```shell
tox devenv -e integration
source venv/bin/activate
```

### Testing

```shell
tox run -e format        # update your code according to linting rules
tox run -e lint          # code style
tox run -e unit          # unit tests
tox -e integration       # integration tests
tox                      # runs 'lint' and 'unit' environments
```

## Canonical Contributor Agreement

Canonical welcomes contributions to the Charmed Kafka Operator. Please check out our [contributor agreement](https://ubuntu.com/legal/contributors) if you're interested in contributing to the solution.
