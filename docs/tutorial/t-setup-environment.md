This is part of the [Charmed Apache Kafka Tutorial](/t/charmed-kafka-tutorial-overview/10571). Please refer to this page for more information and an overview of the content. 

## Setup the environment

For this tutorial, we will need to set up the environment with two main components:

* LXD that is a simple and lightweight virtual machine provisioner
* Juju that will help us to deploy and manage Apache Kafka and related applications

### Prepare LXD

The fastest, simplest way to get started with Charmed Apache Kafka is to set up a local LXD cloud. LXD is a system container and virtual machine manager; Apache Kafka will be run in one of these containers and managed by Juju. While this tutorial covers the basics of LXD, you can [explore more LXD here](https://linuxcontainers.org/lxd/getting-started-cli/). LXD comes pre-installed on Ubuntu 20.04 LTS. Verify that LXD is installed by entering the command `which lxd` into the command line, this will output:

```
/snap/bin/lxd
```

Although LXD is already installed, we need to run `lxd init` to perform post-installation tasks. For this tutorial, the default parameters are preferred and the network bridge should be set to have no IPv6 addresses since Juju does not support IPv6 addresses with LXD:

```shell
lxd init --auto
lxc network set lxdbr0 ipv6.address none
```

You can list all LXD containers by entering the command `lxc list` into the command line. However, at this point of the tutorial, none should exist and you'll only see this as output:

```
+------+-------+------+------+------+-----------+
| NAME | STATE | IPV4 | IPV6 | TYPE | SNAPSHOTS |
+------+-------+------+------+------+-----------+
```

### Install and prepare Juju

[Juju](https://juju.is/) is an Operator Lifecycle Manager (OLM) for clouds, bare metal, LXD or Kubernetes. We will be using it to deploy and manage Apache Kafka. As with LXD, Juju is installed from a snap package:

```shell
sudo snap install juju --channel 3.1/stable
```

Juju already has built-in knowledge of LXD and how it works, so there is no additional setup or configuration needed. A controller will be used to deploy and control Charmed Apache Kafka. All we need to do is run the following command to bootstrap a Juju controller named ‘overlord’ to LXD. This bootstrapping process can take several minutes depending on how provisioned (RAM, CPU, etc.) your machine is:

```shell
juju bootstrap localhost overlord --agent-version 3.1.6
```

The Juju controller should exist within an LXD container. You can verify this by entering the command `lxc list` and you should see the following:

```
+---------------+---------+-----------------------+------+-----------+-----------+
|     NAME      |  STATE  |         IPV4          | IPV6 |   TYPE    | SNAPSHOTS |
+---------------+---------+-----------------------+------+-----------+-----------+
| juju-<id>     | RUNNING | 10.105.164.235 (eth0) |      | CONTAINER | 0         |
+---------------+---------+-----------------------+------+-----------+-----------+
```

where `<id>` is a unique combination of numbers and letters such as `9d7e4e-0`

The controller can work with different models; models host applications such as Charmed Apache Kafka. Set up a specific model for Charmed Apache Kafka named `tutorial`:

```shell
juju add-model tutorial
```

You can now view the model you created above by entering the command `juju status` into the command line. You should see the following:

```
Model    Controller  Cloud/Region         Version  SLA          Timestamp
tutorial overlord    localhost/localhost  3.1.6    unsupported  23:20:53Z

Model "admin/tutorial" is empty.
```