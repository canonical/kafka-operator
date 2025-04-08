# Move Data Between Data Platform Charms using Kafka Connect

In this part of the tutorial, we are going to use [Kafka Connect](https://kafka.apache.org/documentation/#connect) - an ETL framework on top of Apache Kafka - to seamlessly move data between different charmed database technologies.

We will follow a step-by-step process for moving data between [Canonical Data Platform charms](https://canonical.com/data) using Kafka Connect. Specifically, we will showcase a particular use-case of loading data from a relational database, i.e. PostgreSQL, to a document store and search engine, i.e. Opensearch, entirely using charmed solutions.

By the end, you should be able to use Kafka Connect integrator and Kafka Connect charms to streamline data ETL tasks on Canonical Data Platform charmed solutions.

## Prerequisites

We will be deploying different charmed data solutions including PostgreSQL and Opensearch. If you require more information or face issues deploying any of the mentioned products, you should consult the respective documentations:

- For PostgreSQL, refer to [Charmed PostgreSQL tutorial](https://charmhub.io/postgresql/docs/t-overview).
- For Opensearch, refer to [Charmed Opensearch tutorial](https://charmhub.io/opensearch/docs/tutorial).

## 0. Check current deployment

Up to this point, we should have a 3-unit Apache Kafka application, related to a 5-unit ZooKeeper application. That means the `juju status` command should show an output similar to the following:

```shell
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  3.6.4    unsupported  17:06:15+08:00

App                       Version  Status  Scale  Charm                     Channel        Rev  Exposed  Message
data-integrator                    active      1  data-integrator           latest/stable   78  no       
kafka                     3.6.1    active      3  kafka                     3/stable       195  no       
zookeeper                 3.8.4    active      5  zookeeper                 3/stable       149  no       

Unit                         Workload  Agent  Machine  Public address  Ports     Message
data-integrator/0*           active    idle   8        10.38.169.159             
kafka/0                      active    idle   5        10.38.169.139             
kafka/1*                     active    idle   6        10.38.169.92              
kafka/2                      active    idle   7        10.38.169.70              
zookeeper/0*                 active    idle   0        10.38.169.164             
zookeeper/1                  active    idle   1        10.38.169.81              
zookeeper/2                  active    idle   2        10.38.169.72              
zookeeper/3                  active    idle   3        10.38.169.119             
zookeeper/4                  active    idle   4        10.38.169.215             
```

## 1. Set the necessary kernel properties for Opensearch

Since we will be deploying the Opensearch charm, we need to make necessary kernel configurations required for Opensearch charm to function properly, [described in detail here](https://charmhub.io/opensearch/docs/t-set-up#p-24545-set-kernel-parameters). This basically means running the following commands:

```shell
sudo tee -a /etc/sysctl.conf > /dev/null <<EOT
vm.max_map_count=262144
vm.swappiness=0
net.ipv4.tcp_retries2=5
fs.file-max=1048576
EOT

sudo sysctl -p
```

Next, we should set the required model parameters using the `juju model-config` command:

```shell
cat <<EOF > cloudinit-userdata.yaml
cloudinit-userdata: |
  postruncmd:
    - [ 'echo', 'vm.max_map_count=262144', '>>', '/etc/sysctl.conf' ]
    - [ 'echo', 'vm.swappiness=0', '>>', '/etc/sysctl.conf' ]
    - [ 'echo', 'net.ipv4.tcp_retries2=5', '>>', '/etc/sysctl.conf' ]
    - [ 'echo', 'fs.file-max=1048576', '>>', '/etc/sysctl.conf' ]
    - [ 'sysctl', '-p' ]
EOF

juju model-config --file=./cloudinit-userdata.yaml
```

## 2. Deploy the databases and Kafka Connect charms

Deploy the PostgreSQL, Opensearch, and Kafka Connect charms using the following commands. Since the Opensearch charm requires a TLS relation to become active, we will also need to deploy a TLS operator. We will be using the [`self-signed-certificates` charm](https://charmhub.io/self-signed-certificates) in this tutorial:

```shell
juju deploy kafka-connect --channel edge
juju deploy postgresql --channel 14/stable
juju deploy opensearch --channel 2/edge --config profile=testing
juju deploy self-signed-certificates
```

## 3. Make necessary integrations to activate the applications

Using the `juju status` command, you should see that the Kafka Connect and Opensearch applications are in `blocked` state. In order to activate them, we need to make necessary integrations using the `juju integrate` command.

First, activate the Opensearch application by integrating it with the TLS operator:

```shell
juju integrate opensearch self-signed-certificates
```

Then, activate the Kafka Connect application by integrating it with the Apache Kafka application:

```shell
juju integrate kafka kafka-connect
```

Finally, since we will be using TLS on the Kafka Connect interface, integrate the Kafka Connect application with the TLS operator:

```shell
juju integrate kafka-connect self-signed-certificates
```

Use the `juju status --watch 2s` command to continuously probe your model's status. After a couple of minutes, all the applications should be in `active|idle` state, and you should see an output like the following, with 7 applications and 13 units:

```shell
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  3.6.4    unsupported  17:09:25+08:00

App                       Version  Status  Scale  Charm                     Channel        Rev  Exposed  Message
data-integrator                    active      1  data-integrator           latest/stable   78  no       
kafka                     3.6.1    active      3  kafka                     3/stable       195  no       
kafka-connect                      active      1  kafka-connect             latest/edge     13  no       
opensearch                         active      1  opensearch                2/edge         218  no       
postgresql                14.15    active      1  postgresql                14/stable      553  no       
self-signed-certificates           active      1  self-signed-certificates  1/stable       263  no       
zookeeper                 3.8.4    active      5  zookeeper                 3/stable       149  no       

Unit                         Workload  Agent  Machine  Public address  Ports     Message
data-integrator/0*           active    idle   8        10.38.169.159             
kafka-connect/0*             active    idle   9        10.38.169.23    8083/tcp  
kafka/0                      active    idle   5        10.38.169.139             
kafka/1*                     active    idle   6        10.38.169.92              
kafka/2                      active    idle   7        10.38.169.70              
opensearch/0*                active    idle   10       10.38.169.172   9200/tcp  
postgresql/0*                active    idle   12       10.38.169.121   5432/tcp  Primary
self-signed-certificates/0*  active    idle   11       10.38.169.82              
zookeeper/0*                 active    idle   0        10.38.169.164             
zookeeper/1                  active    idle   1        10.38.169.81              
zookeeper/2                  active    idle   2        10.38.169.72              
zookeeper/3                  active    idle   3        10.38.169.119             
zookeeper/4                  active    idle   4        10.38.169.215             
```

## 4. Load some test data into the PostgreSQL database

In a real-world scenario, you will have some application writing data in PostgreSQL database(s). However, for the sake of this tutorial, we will be generating some test data using the SQL script provided in [this GitHub gist](https://gist.github.com/imanenami/bc5900ed2b58e0cc980b498d04677095) and load it into a PostgreSQL database using the `psql` bin command shipped with the PostgreSQL charm.

[Note]
For more information on how to access a PostgreSQL database using the PostgreSQL charm, refer to [Access PostgreSQL](https://charmhub.io/postgresql/docs/t-access) section of the Charmed PostgreSQL tutorial.
[/Note]

First, download the SQL script from the GitHub gist:

```shell
wget https://gist.github.com/imanenami/bc5900ed2b58e0cc980b498d04677095/raw/599599f1f2181e662b7101c5d27db19f423c38f2/populate.sql -O ./populate.sql
```

Next, copy the `populate.sql` script to the PostgreSQL unit using the `juju scp` command:

```shell
juju scp populate.sql postgresql/0:/home/ubuntu/populate.sql
```

Then, following the [Access PostgreSQL](https://charmhub.io/postgresql/docs/t-access) tutorial, grab the `operator` user's password on PostgreSQL database using the `get-password` action:

```shell
juju run postgresql/leader get-password
```

Sample output:

```
...
password: bQOUgw8ZZgUyPA6n
```

Make note of the password, and ssh into the PostgreSQL unit:

```
juju ssh postgresql/leader
```

Once inside the virtual machine, you can use the `psql` command line interface using `operator` user credentials, to create the `tutorial` database:

```shell
psql --host <postgresql-unit-ip> --username operator --password --dbname postgres \
    -c "CREATE DATABASE tutorial"
```

You will be prompted to type the password, which you have obtained previously.

Now, we could use the `populate.sql` script copied earlier into the PostgreSQL unit, to create a table named `posts` with some test data:

```shell
cat /home/ubuntu/populate.sql | \
    psql --host <postgresql-unit-ip> --username operator --password --dbname tutorial
```

To ensure that the test data is loaded successfully into the `posts` table, use the following command:

```shell
psql --host <postgresql-unit-ip> --username operator --password --dbname tutorial \
    -c 'SELECT COUNT(*) FROM posts'
```

Which should have an output like the following, indicating that 5 rows have been added to the `posts` table: 

```shell
 count 
-------
     5
(1 row)
```

Log out from the PostgreSQL unit using `exit` command or the `Ctrl+D` keyboard shortcut.

## 5. Deploy and integrate the `postgresql-connect-integrator` charm

Now that you have some data loaded into PostgreSQL, it is time to deploy the `postgresql-connect-integrator` charm to enable integration of PostgreSQL and Kafka Connect applications. First, deploy the charm using `juju deploy` command and provide the minimum necessary configurations:

```shell
juju deploy postgresql-connect-integrator \
    --channel edge \
    --config mode=source \
    --config db_name=tutorial
    --config topic_prefix=etl_
```

Each Kafka Connect integrator application needs at least two relations to activate: one relation with the Kafka Connect application and one or more relations with Data charms (e.g. MySQL, PostgreSQL, Opensearch, etc.) depending on the use-case.

Therefore, in order to activate this particular integrator charm, use the `juju integrate` command to integrate it with the Kafka Connect and PostgreSQL applications:

```shell
juju integrate postgresql-connect-integrator postgresql
juju integrate postgresql-connect-integrator kafka-connect
```

After a couple of minutes, `juju status` command should show the `postgresql-connect-integrator` in `active|idle` state, with a message indicating that the ETL task is running:

```
...
postgresql-connect-integrator/0*  active    idle   13       10.38.169.83    8080/tcp  Task Status: RUNNING
...
```

This means that the integrator application is actively copying data from the source database, i.e. `tutorial` into Apache Kafka topics prefixed with `etl_`. For example, rows in the `posts` table will be published into an Apache Kafka topic named `etl_posts`.

## 6. Deploy and integrate the `opensearch-connect-integrator` charm

You are almost done with the ETL task, the only remaining part is to move data from Apache Kafka to Opensearch. To achieve that, you need to deploy another Kafka Connect integrator named `opensearch-connect-integrator` in `sink` mode:

```shell
juju deploy opensearch-connect-integrator \
    --channel edge \
    --config mode=sink \
    --config topics="etl_posts"
```

The above command would deploy an integrator application to move messages published into the `etl_posts` topic to an index in Opensearch named `etl_posts`. We know that the `etl_posts` topic is being filled by the `postgresql-connect-integrator` charm we deployed in step 5.

To activate the `opensearch-connect-integrator`, make the necessary integrations:

```shell
juju integrate opensearch-connect-integrator opensearch
juju integrate opensearch-connect-integrator kafka-connect
```

Wait a couple of minutes and run `juju status`, now both `opensearch-connect-integrator` and `postgresql-connect-integrator` applications should be in `active|idle` state, showing a message indicating that the ETL task is running:

```
...
opensearch-connect-integrator/0*  active    idle   14       10.38.169.108   8080/tcp  Task Status: RUNNING
...
postgresql-connect-integrator/0*  active    idle   13       10.38.169.83    8080/tcp  Task Status: RUNNING
...
```

## 7. Verify the data is being copied

Now it's time to verify that the data is being copied from the PostgreSQL database to the Opensearch index. We could use the Opensearch REST API for that purpose.

First, retrieve the admin user credentials for Opensearch using `get-password` action:

```shell
juju run opensearch/leader get-password
```

Sample output:
```
...
password: GoCNE5KdFywT4nF1GSrwpAGyqRLecSXC
username: admin
```

Now, using the password obtained above, send a request to the topic's `_search` endpoint, either using your browser or `curl`:

```shell
curl -u admin:<admin-password> -k -X GET https://<opensearch-unit-ip>:9200/etl_posts/_search
```

You will get a JSON response containing the search results, which should have 5 documents. A truncated sample output is shown below (Note the `hits.total` value which should be 5):

```
{
  "took": 15,
  "timed_out": false, 
  "_shards": {
    "total": 1,
    "successful": 1,
    "skipped": 0,
    "failed": 0
  },
  "hits": {
    "total": {
      "value": 5,
      "relation": "eq"
    },
    "max_score": 1.0,
    "hits": [
      ...
    ]
  }
}

```

Now let's insert a new post into the PostgreSQL database. First ssh into the PostgreSQL leader unit:

```shell
juju ssh postgresql/leader
```

Then, insert a new post using following command and the password you obtained in step 4:

```shell
psql --host <postgresql-unit-ip> --username operator --password --dbname tutorial -c \ 
    "INSERT INTO posts (content, likes) VALUES ('my new post', 1)"
```

Log out from the PostgreSQL unit using `exit` command or the `Ctrl+D` keyboard shortcut.

Then, check that the data is automatically copied to the Opensearch index:

```shell
curl -u admin:<admin-password> -k -X GET https://<opensearch-unit-ip>:9200/etl_posts/_search
```

Which now should have 6 hits (output is truncated):

```
{
...
  "hits": {
    "total": {
      "value": 6,
      "relation": "eq"
    },
...
}
```

Congratualtions! You have successfully deployed an ETL job to move data continuously from PostgreSQL to Opensearch, entirely using charmed solutions.
