This is part of the [Charmed Kafka Tutorial](/t/charmed-kafka-tutorial-overview/10571). Please refer to this page for more information and the overview of the content. 

## Clean up your environment 

If you're done using Charmed Kafka and Juju and would like to free up resources on your machine, you can remove Charmed Kafka, Charmed Zookeeper and Juju. 
*Warning: when you remove Charmed Kafka as shown below you will lose all the data in Kafka. Further, when you remove Juju as shown below you will lose access to any other applications you have hosted on Juju.*

To remove Charmed Kafka and the model it is hosted on run the command:
```shell
juju destroy-model tutorial --destroy-storage --force
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

In this tutorial we've successfully deployed Kafka, added/removed replicas, added/removed users to/from the cluster, and even enabled and disabled TLS. 
You may now keep your Charmed Kafka deployment running or remove it entirely using the steps in [Remove Charmed Kafka and Juju](#remove-charmed-kafka-and-juju). 
If you're looking for what to do next you can:
- Run [Charmed Kafka on Kubernetes](https://github.com/canonical/kafka-k8s-operator).
- Check out our Charmed offerings of [PostgreSQL](https://charmhub.io/postgresql?channel=edge) and [MongoDB](https://charmhub.io/mongodb?channel=5/edge).
- Read about [High Availability Best Practices](https://canonical.com/blog/database-high-availability)
- [Report](https://github.com/canonical/kafka-operator/issues) any problems you encountered.
- [Give us your feedback](https://matrix.to/#/#charmhub-data-platform:ubuntu.com).
- [Contribute to the code base](https://github.com/canonical/kafka-operator)