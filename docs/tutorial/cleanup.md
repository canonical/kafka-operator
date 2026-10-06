(tutorial-cleanup)=
# 7. Cleanup your environment

This is a part of the [Charmed Apache Kafka K8s Tutorial](index.md).

(remove-kafka-and-juju)=
## Remove Charmed Apache Kafka K8s and Juju

If you're done using Charmed Apache Kafka K8s and Juju and would like to free up resources on your machine, you can remove Charmed Apache Kafka K8s, Charmed Apache Zookeeper K8s and Juju.

```{caution}
Removing Charmed Apache Kafka K8s as shown below will delete all the data in the Apache Kafka. Further, when you remove Juju as shown below you lose access to any other applications you have hosted on Juju.
```

To remove Charmed Apache Kafka K8s and the model it is hosted on run the command:

```shell
juju destroy-model tutorial
```

Next step is to remove the Juju controller. You can see all of the available controllers by entering `juju controllers`. To remove the controller enter:

```shell
juju destroy-controller overlord
```

Finally to remove Juju altogether, enter:

```shell
sudo snap remove juju --purge
```

## What's next?

In this tutorial, we've successfully deployed Apache Kafka, added/removed users, connected client applications and even enabled and disabled TLS. 
If you're looking for what to do next you can:

- Run [Charmed Apache Kafka on VMs](https://github.com/canonical/kafka-operator).
- Check out our Charmed offerings of [MySQL](https://charmhub.io/mysql-k8s), [PostgreSQL](https://charmhub.io/postgresql-k8s), [MongoDB](https://charmhub.io/mongodb-k8s).
- Read about [High Availability Best Practices](https://canonical.com/blog/database-high-availability)
- [Report](https://github.com/canonical/kafka-k8s-operator/issues) any problems you encountered.
- [Give us your feedback](https://matrix.to/#/#charmhub-data-platform:ubuntu.com).
- [Contribute to the code base](https://github.com/canonical/kafka-k8s-operator)
