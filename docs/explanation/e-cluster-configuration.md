# Overview of a cluster configuration content

[Apache Kafka](https://kafka.apache.org) is an open-source distributed event streaming platform that requires an external solution to coordinate and sync metadata between all active brokers.
One of such solutions is [ZooKeeper](https://zookeeper.apache.org).

Here are some of the responsibilities of ZooKeeper in a Kafka cluster:

- **Cluster membership**: through regular heartbeats, it keeps tracks of the brokers entering and leaving the cluster, providing an up-to-date list of brokers.
- **Controller election**: one of the Kafka brokers is responsible for managing the leader/follower status for all the partitions. ZooKeeper is used to elect a controller and to make sure there is only one of it.
- **Topic configuration**: each topic can be replicated on multiple partitions. ZooKeeper keeps track of the locations of the partitions and replicas, so that high-availability is still attained when a broker shuts down. Topic-specific configuration overrides (e.g. message retention and size) are also stored in ZooKeeper.
- **Access control and authentication**: ZooKeeper stores access control lists (ACL) for Kafka resources, to ensure only the proper, authorized, users or groups can read or write on each topic.

The values for the configuration parameters mentioned above are stored in znodes, the hierarchical unit data structure in ZooKeeper.
A znode is represented by its path and can both have data associated with it and children nodes.
ZooKeeper clients interact with its data structure similarly to a remote file system that would be sync-ed between the ZooKeeper units for high availability.
For a Charmed Kafka related to a Charmed ZooKeeper:
- the list of the broker ids of the cluster can be found in `/kafka/brokers/ids`
- the endpoint used to access the broker with id `0` can be found in `/kafka/brokers/ids/0`
- the credentials for the Charmed Kafka users can be found in `/kafka/config/users`