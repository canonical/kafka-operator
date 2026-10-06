(tutorial-environment)=
# 1. Set up the environment

This is part of the [Charmed Apache Kafka K8s Tutorial](index.md).

[Multipass](https://multipass.run/) is a quick and easy way to launch virtual machines running Ubuntu. It uses "[{spellexception}`cloud-init`](https://cloud-init.io/)" standard to install and configure all the necessary parts automatically.

## Prepare Multipass

Let's install Multipass from [Snap](https://snapcraft.io/multipass) and launch a new VM using "[{spellexception}`charm-dev`](https://github.com/canonical/multipass-blueprints/blob/main/v1/charm-dev.yaml)" cloud-init configuration:

```shell
sudo snap install multipass && \
multipass launch --cpus 4 --memory 8G --disk 50G --name my-vm charm-dev
```

*Note: See all `multipass launch` parameters in the [launch command documentation](https://multipass.run/docs/launch-command)*.

Multipass [list of commands](https://multipass.run/docs/multipass-cli-commands) is short and self-explanatory, e.g. show all running VMs:

```shell
multipass list
```

As soon as the new VM starts, enter:

```shell
multipass shell my-vm
```

*Note: if at any point you'd like to leave Multipass VM, use `Ctrl+D` or type `exit`*.

## Prepare Juju

All the parts have been pre-installed inside VM already, like MicroK8s, LXD and Juju (the files `/var/log/cloud-init.log` and `/var/log/cloud-init-output.log` contain all low-level installation details). 
Also, the image already comes with two Juju controllers already setup, one for LXD and one for MicroK8s

```shell
$ juju list-controllers
Use --refresh option with this command to see the latest information.

Controller  Model     User   Access     Cloud/Region         Models  Nodes    HA  Version
lxd*        tutorial  admin  superuser  localhost/localhost       2      1  none  3.1.5
microk8s    -         admin  superuser  microk8s/localhost        1      1     -  3.1.5
```

Make sure that you use the controller bound to the MicroK8s cluster, e.g.:

```shell
juju switch microk8s
```

The Juju controller can work with different models; models host applications such as Charmed Apache Kafka K8s. Set up a specific model for Charmed Apache Kafka K8s named `tutorial`:

```shell
juju add-model tutorial
```

You can now view the model you created above by entering the command `juju status` into the command line. You should see the following:

```text
Model     Controller  Cloud/Region        Version  SLA          Timestamp
tutorial  microk8s    microk8s/localhost  3.1.5    unsupported  15:46:55+02:00

Model "admin/tutorial" is empty.
```
