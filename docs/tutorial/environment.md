---
myst:
  html_meta:
    description: "Set up your development environment for Charmed Apache Kafka using LXD, Juju, and command-line tools on Ubuntu."
---

<!-- test:spread
priority: 300
kill-timeout: 15m
-->

(tutorial-environment)=
# 1. Set up the environment

This is a part of the [Charmed Apache Kafka Tutorial](index.md).

For this tutorial, we will need to set up the environment with two main components, and extra command-line tooling:

* A cloud provisioner -- [LXD](https://github.com/canonical/lxd) for the VM
  substrate, or [MicroK8s](https://microk8s.io/) for the Kubernetes substrate
* [Juju](https://github.com/juju/juju) - enables us to deploy and manage Charmed Apache Kafka and related applications
* [yq](https://github.com/mikefarah/yq) - a command-line YAML processor
* [jq](https://github.com/jqlang/jq) - a command-line JSON processor

## Prepare the cloud

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

The fastest, simplest way to get started with Charmed Apache Kafka is to set up a local LXD cloud.
LXD is a system container and virtual machine manager;
Apache Kafka will be run in one of these containers and managed by Juju.
While this tutorial covers the basics of LXD, you can
[learn more about LXD here](https://canonical.com/lxd/docs/stable-5.21/).

LXD comes pre-installed on Ubuntu 24.04 LTS. Verify that LXD is installed by entering the command
`which lxd`. This will output `/snap/bin/lxd` or, for some systems, `/usr/sbin/lxd`.

Although LXD is already installed, we need to run `lxd init` to perform post-installation tasks.
For this tutorial, the default parameters are preferred and the network bridge should be set
to have no IPv6 addresses since Juju does not support IPv6 addresses with LXD:

```shell
lxd init --auto
lxc network set lxdbr0 ipv6.address none
```

You can list all LXD containers by entering the command `lxc list` into the command line. However, at this point of the tutorial, none should exist and you'll only see this as output:

```text
+------+-------+------+------+------+-----------+
| NAME | STATE | IPV4 | IPV6 | TYPE | SNAPSHOTS |
+------+-------+------+------+------+-----------+
```

````

````{tab-item} K8s
:sync: k8s

For the Kubernetes substrate, the simplest way to get started is a local
MicroK8s cloud. Apache Kafka will run in pods on this cluster and be managed
by Juju.

Install MicroK8s and add your user to its group:

```bash
sudo snap install microk8s --channel 1.32-strict/stable
sudo usermod -a -G snap_microk8s $USER
newgrp snap_microk8s
```

Enable the add-ons required by Charmed Apache Kafka K8s. The `hostpath-storage`
add-on provides the persistent volumes used by broker storage:

```bash
sudo microk8s enable dns hostpath-storage
sudo microk8s status --wait-ready
```

```{caution}
`hostpath-storage` is suitable for this tutorial only. Production deployments
require a proper storage class -- see the
[deployment guide](how-to-deploy-anywhere).
```

List all pods to confirm the cluster is running. At this point of the tutorial,
only system pods should exist:

```bash
sudo microk8s kubectl get pods -A
```

````

`````

## Install and prepare Juju

[Juju](https://juju.is/) is an Operator Lifecycle Manager (OLM) for clouds, bare metal,
LXD or Kubernetes. We will be using it to deploy and manage Charmed Apache Kafka.
As may be true for LXD, Juju is installed from a snap package:

```shell
sudo snap install juju
```

Install `yq`, a YAML processor used to parse Juju output in later steps:

```shell
sudo snap install yq
```

Install `jq`, a JSON processor used in later steps:

```shell
sudo snap install jq
```

Juju already has built-in knowledge of LXD and MicroK8s and how they work, so
there is no additional cloud setup or configuration needed. A Juju controller
will be deployed, which will in turn manage the operations of Charmed Apache
Kafka. All we need to do is bootstrap a Juju controller named `overlord`. This
bootstrapping process can take several minutes depending on the resources
available on your machine:

`````{tab-set}
:sync-group: substrate

````{tab-item} VM
:sync: vm

```shell
juju bootstrap localhost overlord
```

The Juju controller exists within an LXD container.
To verify this, check the list of containers:

```shell
lxc list
```

<details> <summary> Output example</summary>

```text
+---------------+---------+-----------------------+------+-----------+-----------+
|     NAME      |  STATE  |         IPV4          | IPV6 |   TYPE    | SNAPSHOTS |
+---------------+---------+-----------------------+------+-----------+-----------+
| juju-<id>     | RUNNING | 10.105.164.235 (eth0) |      | CONTAINER | 0         |
+---------------+---------+-----------------------+------+-----------+-----------+
```

where `<id>` is a unique combination of numbers and letters such as `9d7e4e-0`.

</details>

````

````{tab-item} K8s
:sync: k8s

```bash
juju bootstrap microk8s overlord
```

The Juju controller runs as a pod in the `controller-overlord` namespace.
To verify this, list the pods:

```bash
sudo microk8s kubectl get pods -n controller-overlord
```

<details> <summary> Output example</summary>

```text
NAME           READY   STATUS    RESTARTS   AGE
controller-0   3/3     Running   0          2m
```

</details>

````

`````

The controller can work with different models;
models host applications such as Charmed Apache Kafka.
Set up a specific model for Charmed Apache Kafka named `tutorial`:

```shell
juju add-model tutorial
```

Check the status of the model you created:

```shell
juju status
```

<!-- test:assert
juju models | grep -q tutorial
-->

<details> <summary> Output example</summary>

```text
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  3.6.13   unsupported  12:10:54Z

Model "admin/tutorial" is empty.
```

</details>
