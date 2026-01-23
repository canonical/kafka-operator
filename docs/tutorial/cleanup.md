(tutorial-cleanup)=
# 8. Cleanup your environment

This is a part of the [Charmed Apache Kafka Tutorial](index.md).

(remove-kafka-and-juju)=
## Remove tutorial

```{caution}
Removing a Juju model may result in data loss for all applications in this model.
```

To remove Charmed Apache Kafka and the `tutorial` model it is hosted on,
along with all other applications:

```shell
juju destroy-model tutorial --destroy-storage --force
```

This will remove all applications in the `tutorial` model (Charmed Apache Kafka, 
OpenSearch, PostgreSQL).
Your Juju controller and other models (if any) will remain intact for future use.

(remove-juju)=
## (Optional) Remove Juju and LXD

If you don't need Juju anymore and want to free up additional resources on your machine,
you can remove the Juju controller and Juju itself.

```{caution}
When you remove Juju as shown below,
you lose access to any other applications you have hosted on Juju.
```

### Remove the Juju controller

Check the list of controllers:

```shell
juju controllers
```

Remove the Juju controller created in this tutorial:

```shell
juju destroy-controller overlord
```

### Remove Juju

To remove Juju altogether:

```shell
sudo snap remove juju --purge
```

### Clean up LXD

If you also want to remove LXD containers and free up all resources:

List all remaining LXD containers:

```shell
lxc list
```

Delete unnecessary containers:

```shell
lxc delete <container-name> --force
```

If you want to uninstall LXD completely:

```shell
sudo snap remove lxd --purge
```

```{warning}
Only remove LXD if you're not using it for other purposes.
LXD may be managing other containers or VMs on your system.
```

## What's next?

In this tutorial, we've successfully deployed Apache Kafka, added/removed replicas, added/removed users to/from the cluster, and even enabled and disabled TLS.
You may now keep your Charmed Apache Kafka deployment running or remove it entirely using the steps in [Remove Charmed Apache Kafka and Juju](remove-kafka-and-juju).
If you're looking for what to do next you can:

- Run [Charmed Apache Kafka on Kubernetes](https://github.com/canonical/kafka-k8s-operator).
- Check out our other Charmed offerings from [Canonical's Data Platform team](https://canonical.com/data)
- Read about [High Availability Best Practices](https://canonical.com/blog/database-high-availability)
- [Report](https://github.com/canonical/kafka-operator/issues) any problems you encountered.
- [Give us your feedback](https://matrix.to/#/#charmhub-data-platform:ubuntu.com).
- [Contribute to the code base](https://github.com/canonical/kafka-operator)
