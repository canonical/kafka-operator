# Cluster configuration

[Apache Kafka](https://kafka.apache.org) is an open-source distributed event streaming platform that requires an external solution to coordinate and sync metadata between all active brokers.
One of such solutions is [Apache ZooKeeper](https://zookeeper.apache.org).

Here are some of the responsibilities of Apache ZooKeeper in an Apache Kafka cluster:

- **Cluster membership**: through regular heartbeats, it keeps track of the brokers entering and leaving the cluster, providing an up-to-date list of brokers.
- **Controller election**: one of the Apache Kafka brokers is responsible for managing the leader/follower status for all the partitions. Apache ZooKeeper is used to elect a controller and to make sure there is only one of it.
- **Topic configuration**: each topic can be replicated on multiple partitions. Apache ZooKeeper keeps track of the locations of the partitions and replicas so that high availability is still attained when a broker shuts down. Topic-specific configuration overrides (e.g. message retention and size) are also stored in Apache ZooKeeper.
- **Access control and authentication**: Apache ZooKeeper stores access control lists (ACL) for Apache Kafka resources, to ensure only the proper, authorized, users or groups can read or write on each topic.

The values for the configuration parameters mentioned above are stored in znodes, the hierarchical unit data structure in Apache ZooKeeper.
A znode is represented by its path and can both have data associated with it and children nodes.
Apache ZooKeeper clients interact with its data structure similarly to a remote file system that would be synced between the Apache ZooKeeper units for high availability.
For a Charmed Apache Kafka related to a Charmed Apache ZooKeeper:

- the list of the broker ids of the cluster can be found in `/kafka/brokers/ids`
- the endpoint used to access the broker with id `0` can be found in `/kafka/brokers/ids/0`
- the credentials for the Apache Kafka users can be found in `/kafka/config/users`