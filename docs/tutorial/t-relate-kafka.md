# Relate your Kafka deployment 

This is part of the [Charmed Kafka Tutorial](/t/charmed-kafka-tutorial-overview/10571). Please refer to this page for more information and the overview of the content. 

## Relations
Relations, or what Juju documentation [describes as Integration](https://juju.is/docs/sdk/integration), are the easiest way to create a user for Kafka in Charmed Kafka. Relations automatically create a username, password, and topic for the desired user/application. 

### Data Integrator Charm
To start using the Kafka cluster, we will now relate our application to the [Data Integrator Charm](https://charmhub.io/data-integrator). This is a bare-bones charm that allows for central management of database users, providing support for different kinds of data platforms (e.g. MongoDB, MySQL, PostgreSQL, Kafka, OpenSearch, etc) with a consistent, opinionated and robust user experience. In order to deploy the Data Integrator Charm we can use the command `juju deploy` we have learned above:

```shell
juju deploy data-integrator --channel stable --config topic-name=test-topic --config extra-user-roles=producer,consumer
```
The expected output:
```shell
Located charm "data-integrator" in charm-hub, revision 11
Deploying "data-integrator" from charm-hub charm "data-integrator", revision 11 in channel stable on jammy
```

### Relate to Kafka
Now that the Database Integrator Charm has been set up, we can relate it to Kafka. This will automatically create a username, password, and database for the Database Integrator Charm. Relate the two applications with:
```shell
juju relate data-integrator kafka
```
Wait for `juju status --watch 1s` to show:
```shell
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  2.9.38   unsupported  10:04:50Z

App              Version  Status  Scale  Charm            Channel      Rev  Exposed  Message
data-integrator           active      1  data-integrator  stable        11  no       
kafka                     active      3  kafka            3/stable     117  no       
zookeeper                 active      5  zookeeper        3/stable      99  no       

Unit                Workload  Agent  Machine  Public address  Ports  Message
data-integrator/0*  active    idle   8        10.244.26.4            
kafka/0             active    idle   5        10.244.26.43           machine system settings are not optimal - see logs for info
kafka/1*            active    idle   6        10.244.26.6            machine system settings are not optimal - see logs for info
kafka/2             active    idle   7        10.244.26.19           machine system settings are not optimal - see logs for info
zookeeper/0         active    idle   0        10.244.26.251          
zookeeper/1         active    idle   1        10.244.26.129          
zookeeper/2         active    idle   2        10.244.26.121          
zookeeper/3*        active    idle   3        10.244.26.28           
zookeeper/4         active    idle   4        10.244.26.174          

Machine  State    Address        Inst id        Series  AZ  Message
0        started  10.244.26.251  juju-f1a2cd-0  jammy       Running
1        started  10.244.26.129  juju-f1a2cd-1  jammy       Running
2        started  10.244.26.121  juju-f1a2cd-2  jammy       Running
3        started  10.244.26.28   juju-f1a2cd-3  jammy       Running
4        started  10.244.26.174  juju-f1a2cd-4  jammy       Running
5        started  10.244.26.43   juju-f1a2cd-5  jammy       Running
6        started  10.244.26.6    juju-f1a2cd-6  jammy       Running
7        started  10.244.26.19   juju-f1a2cd-7  jammy       Running
8        started  10.244.26.4    juju-f1a2cd-8  jammy       Running
```
To retrieve information such as the username, password, and topic. Enter:
```shell
juju run-action data-integrator/leader get-credentials --wait
```
This should output something like:
```yaml
​unit-data-integrator-0:
  UnitId: data-integrator/0
  id: "4"
  results:
    kafka:
      consumer-group-prefix: relation-6-
      endpoints: 10.244.26.43:9092,10.244.26.6:9092,10.244.26.19:9092
      password: ILg8C5msYRvqOnGATeFPyw2DKHncritf
      tls: disabled
      topic: test-topic
      username: relation-6
      zookeeper-uris: 10.244.26.121:2181,10.244.26.129:2181,10.244.26.174:2181,10.244.26.251:2181,10.244.26.28:2181/kafka
    ok: "True"
  status: completed
  timing:
    completed: 2023-04-25 10:09:26 +0000 UTC
    enqueued: 2023-04-25 10:09:20 +0000 UTC
    started: 2023-04-25 10:09:21 +0000 UTC
```

Save the value listed under `bootstrap-server`, `username` and `password`. *(Note: your hostnames, usernames, and passwords will likely be different.)*

### Remove the user
To remove the user, remove the relation. Removing the relation automatically removes the user that was created when the relation was created. Enter the following to remove the relation:
```shell
juju remove-relation kafka data-integrator
```

The output of the juju model should be something like this:

```shell
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  2.9.38   unsupported  10:20:59Z

App              Version  Status   Scale  Charm            Channel      Rev  Exposed  Message
data-integrator           blocked      1  data-integrator  stable        11  no       Please relate the data-integrator with the desired product
kafka                     active       3  kafka            3/stable     117  no       
zookeeper                 active       5  zookeeper        3/stable      99  no       

Unit                Workload  Agent  Machine  Public address  Ports  Message
data-integrator/0*  blocked   idle   8        10.244.26.4            Please relate the data-integrator with the desired product
kafka/0             active    idle   5        10.244.26.43           
kafka/1*            active    idle   6        10.244.26.6            
kafka/2             active    idle   7        10.244.26.19           
zookeeper/0         active    idle   0        10.244.26.251          
zookeeper/1         active    idle   1        10.244.26.129          
zookeeper/2         active    idle   2        10.244.26.121          
zookeeper/3*        active    idle   3        10.244.26.28           
zookeeper/4         active    idle   4        10.244.26.174          

Machine  State    Address        Inst id        Series  AZ  Message
0        started  10.244.26.251  juju-f1a2cd-0  jammy       Running
1        started  10.244.26.129  juju-f1a2cd-1  jammy       Running
2        started  10.244.26.121  juju-f1a2cd-2  jammy       Running
3        started  10.244.26.28   juju-f1a2cd-3  jammy       Running
4        started  10.244.26.174  juju-f1a2cd-4  jammy       Running
5        started  10.244.26.43   juju-f1a2cd-5  jammy       Running
6        started  10.244.26.6    juju-f1a2cd-6  jammy       Running
7        started  10.244.26.19   juju-f1a2cd-7  jammy       Running
8        started  10.244.26.4    juju-f1a2cd-8  jammy       Running
```