---
relatedlinks: "[GitHub](https://github.com/canonical/kafka-operator), [Charmhub](https://charmhub.io/kafka), [Charmhub&#32;(K8s)](https://charmhub.io/kafka-k8s)"
myst:
  html_meta:
    description: "How to contribute to Charmed Apache Kafka - report issues, contribute code and documentation, get in touch with the team, and learn about Canonical career opportunities."
---

(contributing-guide)=
# How to contribute

Charmed Apache Kafka is an open-source project developed and supported by
[Canonical](https://canonical.com/) that welcomes community contributions,
suggestions, fixes, and constructive feedback.

If you would like to contribute a larger change, please [get in touch](contributing-contact)
with us first so we can help you shape the contribution.

## Report an issue

Report bugs and feature requests on
[GitHub](https://github.com/canonical/kafka-operator/issues/new). For
documentation issues, use the **Give feedback** button at the top of the
relevant page to open a pre-filled GitHub issue.

```{note}
Please do **not** use GitHub issues for security topics. See
{ref}`the section below <contributing-security>`.
```

(contributing-security)=
### Report a security issue

Security issues should be reported through
[Launchpad](https://wiki.ubuntu.com/DebuggingSecurity#How_to_File), following
the Ubuntu security disclosure process. Please do **not** file GitHub issues
on security topics.

See also [SECURITY.md](https://github.com/canonical/kafka-operator/blob/main/SECURITY.md)
in the repository.

(contributing-contact)=
## Get in touch

If you have questions after reading this documentation or would like to discuss
Charmed Apache Kafka, get in touch through one of the following channels:

* Chat with the Data team directly on
  [Matrix](https://matrix.to/#/#charmhub-data-platform:ubuntu.com).
* Ask questions and share feedback on the
  [Discourse forum](https://discourse.charmhub.io/tag/kafka).
* To talk to Canonical about your use case or commercial support, use the
  [business form](https://canonical.com/data/kafka#get-in-touch).

(contributing-code)=
## Contribute code

If you would like to contribute, the following sections
cover the building and testing for both source code and documentation.

This repository contains both the machine (VM) charm (`machine/`) and the
Kubernetes (K8s) charm (`k8s/`), along with their Kafka Connect counterparts
(`connect_machine/` and `connect_k8s/`). Instructions below apply to both
substrates; VM/K8s differences are called out with separate tabs or notes.

### Requirements

To build the charm locally, you will need to install
[Charmcraft](https://snapcraft.io/charmcraft).

To run the **VM** charm locally with Juju, it is recommended to use
[LXD](https://linuxcontainers.org/lxd/introduction/) as your virtual machine
manager. Instructions for running Juju on LXD can be found
[here](https://canonical.com/juju/docs/juju-cli/3.6/reference/cloud/list-of-supported-clouds/lxd/).

To run the **K8s** charm locally with Juju, you will additionally need a
Kubernetes cluster registered with Juju, such as
[MicroK8s](https://microk8s.io/) (`1.32-strict/stable` with the `dns` and
`hostpath-storage` addons enabled).

### Build and deploy

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

To build and deploy the machine charm:

```bash
# Clone and enter the repository
git clone https://github.com/canonical/kafka-operator.git
cd kafka-operator/machine

# Create a working model
juju add-model kafka

# Enable DEBUG logging for the model
juju model-config logging-config="<root>=INFO;unit=DEBUG"

# Build the charm locally
CHARMCRAFT_EXPERIMENTAL_MONOREPO=true charmcraft pack

# Deploy the charm
juju deploy ./*.charm -n 3 --config roles=broker,controller
```

````

````{tab-item} K8s
:sync: k8s

To build and deploy the K8s charm:

```bash
# Clone and enter the repository
git clone https://github.com/canonical/kafka-operator.git
cd kafka-operator/k8s

# Switch to a Kubernetes-backed controller and create a working model
juju switch <k8s-controller>
juju add-model kafka

# Enable DEBUG logging for the model
juju model-config logging-config="<root>=INFO;unit=DEBUG"

# Build the charm locally
CHARMCRAFT_EXPERIMENTAL_MONOREPO=true charmcraft pack

# Deploy the charm
juju deploy ./*.charm -n 3 --config roles=broker,controller --trust
```

The `--trust` flag is required so Juju can manage the Kubernetes resources
(Services, StatefulSet) the charm creates.

````

`````

### Develop and test

You can create an environment for development with `tox`:

```bash
tox devenv -e integration
source venv/bin/activate
poetry install --with integration
```

Run the test suites with:

```bash
tox run -e format        # update your code according to linting rules
tox run -e lint          # code style
tox run -e unit          # unit tests (both VM and K8s substrates)
tox run -e integration   # integration tests
tox                      # runs 'lint' and 'unit' environments
```

Integration tests are split by substrate using the `integration-machine-*`
and `integration-k8s-*` tox environments, for example:

```bash
tox run -e integration-machine-charm   # VM
tox run -e integration-k8s-charm       # K8s
```

The tutorial end-to-end test suite (requires
[Multipass](https://documentation.ubuntu.com/multipass/) and
[Spread](https://github.com/canonical/spread)) covers the **VM charm only**
and can be run with:

```bash
tox -e tutorial           # extract scripts + run Spread tests
tox -e tutorial-extract   # generate test scripts only
```

See [tests/tutorial/TESTING.md](https://github.com/canonical/kafka-operator/blob/main/tests/tutorial/TESTING.md)
for full setup instructions and run modes.

### Review process

All enhancements require review before being merged. Code review typically
examines code quality, test coverage, and the user experience for Juju
administrators of this charm.

Please help us out in ensuring easy-to-review branches by rebasing your pull
request branch onto the `main` branch. This also avoids merge commits and
creates a linear Git commit history.

Familiarising yourself with the
[Ops framework](https://canonical.com/juju/docs/ops/latest/) will help you when
working on new features or bug fixes.

(contributing-docs)=
## Contribute documentation

The documentation lives in the `docs/` folder of this repository and is built
with [Sphinx](https://www.sphinx-doc.org/) from MyST Markdown sources. It is
published on Read the Docs.

### Prerequisites

* A [GitHub account](https://docs.github.com/en/get-started/start-your-journey/creating-an-account-on-github).
* Compliance with the {ref}`Code of Conduct <contributing-code-of-conduct>`.

### Report a documentation issue

To report an issue with spelling, grammar, or technical content,
[file an issue on GitHub](https://github.com/canonical/kafka-operator/issues/new)
or use the **Give feedback** button at the top of the affected page.

### Make a contribution

For a quick fix — a typo, a broken link, a small clarification — the easiest
way is to click the pencil icon at the top of the documentation page (next to
the **Give feedback** button). It takes you to the GitHub web editor for that
page, where you can submit a pull request directly through the web interface.

For larger contributions:

1. Create a branch (in the main repository or in a fork) from the current
   `main` and modify the documentation files as necessary.
2. Raise a pull request against `main` to start the review process.
3. Once the pull request is approved and all comments are addressed, it can
   be merged.

To preview and test the documentation locally:

```bash
cd docs
make run        # live-reload build served on http://127.0.0.1:8000
```

Before submitting, make sure the following checks pass:

```bash
cd docs
make html       # full build; fails on warnings
make linkcheck  # verify all external links
make lint-md    # Markdown linting
make spelling   # Vale spelling check
make woke       # inclusive-language check
```

```{note}
The pages under `docs/reference/_generated/` are generated automatically from
the charm source files (`actions.yaml`, `config.yaml`, and the status
literals) and must not be edited by hand.
```

The documentation follows the [Diátaxis structure](https://diataxis.fr/):
tutorials, how-to guides, reference, and explanation each live in their own
section and should not be mixed. For terminology and trademark conventions,
see {ref}`the trademarks explanation <explanation-trademarks>`.

## Code of conduct

(contributing-code-of-conduct)=
This project follows the
[Ubuntu Code of Conduct](https://ubuntu.com/community/code-of-conduct).
Maintainers reserve the right to remove any contributions that do not respect
it.

## Contributor agreement

Canonical welcomes contributions to Charmed Apache Kafka. Please check out our
[contributor agreement](https://ubuntu.com/legal/contributors) if you're
interested in contributing to the solution.

## We are hiring!

Also, if you truly enjoy working on open-source projects like this one, check
out the [career options](https://canonical.com/careers/all) we have at
[Canonical](https://canonical.com/).

## Useful links

* [Canonical Data solutions](https://canonical.com/data)
* [Charmed Apache Kafka](https://charmhub.io/kafka)
* [Git sources for Charmed Apache Kafka](https://github.com/canonical/kafka-operator)
* [Canonical Data on Launchpad](https://launchpad.net/~data-platform)
* [Canonical Data on Matrix](https://matrix.to/#/#charmhub-data-platform:ubuntu.com)
