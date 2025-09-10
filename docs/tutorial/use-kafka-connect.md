(tutorial-kafka-connect)=
# 7. Use Kafka Connect for ETL

This is a part of the [Charmed Apache Kafka Tutorial](index.md).

## Using Kafka Connect for ETL

In this part of the tutorial, we are going to use [Kafka Connect](https://kafka.apache.org/documentation/#connect) - an ETL framework on top of Apache Kafka - to seamlessly move data between different charmed database technologies.

We will follow a step-by-step process for moving data between [Canonical Data Platform charms](https://canonical.com/data) using Kafka Connect. Specifically, we will showcase a particular use-case of loading data from a relational database, i.e. PostgreSQL, to a document store and search engine, i.e. OpenSearch, entirely using charmed solutions.

By the end, you should be able to use Kafka Connect integrator and Kafka Connect charms to streamline data ETL tasks on Canonical Data Platform charmed solutions.

### Prerequisites

We will be deploying different charmed data solutions including PostgreSQL and OpenSearch. If you require more information or face issues deploying any of the mentioned products, you should consult the respective documentations:

- For PostgreSQL, refer to [Charmed PostgreSQL tutorial](https://canonical-charmed-postgresql.readthedocs-hosted.com/14/tutorial/).
- For OpenSearch, refer to [Charmed OpenSearch tutorial](https://charmhub.io/opensearch/docs/tutorial).

### Check current deployment

Up to this point, we should have three units of Charmed Apache Kafka application. That means the `juju status` command should show an output similar to the following:

```text
Model     Controller        Cloud/Region         Version  SLA          Timestamp
tutorial  overlord          localhost/localhost  3.6.8    unsupported  01:02:27Z

App                       Version  Status  Scale  Charm                     Channel        Rev  Exposed  Message
data-integrator                    active      1  data-integrator           latest/stable  180  no       
kafka                     4.0.0    active      3  kafka                     4/edge         226  no       
kraft                     4.0.0    active      3  kafka                     4/edge         226  no       
self-signed-certificates           active      1  self-signed-certificates  1/edge         336  no       

Unit                         Workload  Agent  Machine  Public address  Ports           Message
data-integrator/0*           active    idle   6        10.233.204.111                  
kafka/0*                     active    idle   0        10.233.204.241  9093,19093/tcp  
kafka/1                      active    idle   1        10.233.204.196  9093,19093/tcp  
kafka/2                      active    idle   2        10.233.204.148  9093,19093/tcp  
kraft/0                      active    idle   3        10.233.204.125  9098/tcp        
kraft/1*                     active    idle   4        10.233.204.36   9098/tcp        
kraft/2                      active    idle   5        10.233.204.225  9098/tcp        
self-signed-certificates/0*  active    idle   7        10.233.204.134                  
```

### Set the necessary kernel properties for OpenSearch

Since we will be deploying the OpenSearch charm, we need to make necessary kernel configurations required for OpenSearch charm to function properly, [described in detail here](https://charmhub.io/opensearch/docs/t-set-up#p-24545-set-kernel-parameters). This basically means running the following commands:

```bash
sudo tee -a /etc/sysctl.conf > /dev/null <<EOT
vm.max_map_count=262144
vm.swappiness=0
net.ipv4.tcp_retries2=5
fs.file-max=1048576
EOT

sudo sysctl -p
```

Next, we should set the required model parameters using the `juju model-config` command:

```bash
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

### Deploy the databases and Kafka Connect charms

Deploy the PostgreSQL, OpenSearch, and Kafka Connect charms:

```bash
juju deploy kafka-connect --channel edge
juju deploy postgresql --channel 14/stable
juju deploy opensearch --channel 2/stable --config profile=testing
```

OpenSearch charm requires a TLS relation to become active. We will use the [`self-signed-certificates` charm](https://charmhub.io/self-signed-certificates) that was deployed earlier in the [Enable Encryption](https://charmhub.io/kafka/docs/t-enable-encryption) part of this Tutorial.

### Enable TLS

Using the `juju status` command, you should see that the Kafka Connect and OpenSearch applications are in `blocked` state. In order to activate them, we need to make necessary integrations using the `juju integrate` command.

First, activate the OpenSearch application by integrating it with the TLS operator:

```bash
juju integrate opensearch self-signed-certificates
```

Then, activate the Kafka Connect application by integrating it with the Apache Kafka application:

```bash
juju integrate kafka kafka-connect
```

Finally, since we will be using TLS on the Kafka Connect interface, integrate the Kafka Connect application with the TLS operator:

```bash
juju integrate kafka-connect self-signed-certificates
```

Use the `watch -n 1 --color juju status --color` command to continuously probe your model's status. After a couple of minutes, all the applications should be in `active|idle` state, and you should see an output like the following, with 7 applications and 13 units:

```text
Model     Controller        Cloud/Region         Version  SLA          Timestamp
tutorial  overlord          localhost/localhost  3.6.8    unsupported  01:02:27Z

App                       Version  Status  Scale  Charm                     Channel        Rev  Exposed  Message
data-integrator                    active      1  data-integrator           latest/stable  180  no       
kafka                     4.0.0    active      3  kafka                     4/edge         226  no       
kraft                     4.0.0    active      3  kafka                     4/edge         226  no       
opensearch                         active      1  opensearch                2/edge         218  no       
postgresql                14.15    active      1  postgresql                14/stable      553  no       

self-signed-certificates           active      1  self-signed-certificates  1/edge         336  no       

Unit                         Workload  Agent  Machine  Public address  Ports           Message
data-integrator/0*           active    idle   6        10.233.204.111                  
opensearch/0*                active    idle   11       10.233.204.172  9200/tcp  
postgresql/0*                active    idle   12       10.233.204.121  5432/tcp        Primary
kafka/0*                     active    idle   0        10.233.204.241  9093,19093/tcp  
kafka/1                      active    idle   1        10.233.204.196  9093,19093/tcp  
kafka/2                      active    idle   2        10.233.204.148  9093,19093/tcp  
kraft/0                      active    idle   3        10.233.204.125  9098/tcp        
kraft/1*                     active    idle   4        10.233.204.36   9098/tcp        
kraft/2                      active    idle   5        10.233.204.225  9098/tcp        
self-signed-certificates/0*  active    idle   7        10.233.204.134                  
```

### Load test data

In a real-world scenario, an application would typically write data to a PostgreSQL database. However, for the purposes of this tutorial, we’ll generate test data using a simple SQL script and load it into a PostgreSQL database using the `psql` command-line tool included with the PostgreSQL charm.

```{note}
For more information on how to access a PostgreSQL database in the PostgreSQL charm, refer to [Access PostgreSQL](https://charmhub.io/postgresql/docs/t-access) page of the Charmed PostgreSQL tutorial.
```

First, create a SQL script by running the following command:

```bash
cat <<EOF > /tmp/populate.sql
CREATE TABLE posts (
  id serial not null primary key,
  content text not null,
  likes int default null,
  created_at timestamp with time zone not null default now()
);

INSERT INTO posts (content, likes) 
VALUES 
  (
    'Charmed Apache Kafka is an open-source operator that makes it easier to manage Apache Kafka, with built-in support for enterprise features.', 
    150
  ), 
  (
    'Apache Kafka is a free, open-source software project by the Apache Software Foundation. Users can find out more at the Apache Kafka project page.', 
    200
  ), 
  (
    'Charmed Apache Kafka is built on top of Juju and reliably simplifies the deployment, scaling, design, and management of Apache Kafka in production', 
    100
  ), 
  (
    'Charmed Apache Kafka is a solution designed and developed to help ops teams and administrators automate Apache Kafka operations from Day 0 to Day 2, across multiple cloud environments and platforms.', 
    1000
  ), 
  (
    'Charmed Apache Kafka is developed and supported by Canonical, as part of its commitment to provide open-source, self-driving solutions, seamlessly integrated using the Operator Framework Juju. Please refer to Charmhub, for more charmed operators that can be integrated by Juju.', 
    60
  );
EOF
```

Next, copy the `populate.sql` script to the PostgreSQL unit using the `juju scp` command:

```bash
juju scp /tmp/populate.sql postgresql/0:/home/ubuntu/populate.sql
```

Then, follow the [Access PostgreSQL](https://charmhub.io/postgresql/docs/t-access) tutorial to retrieve the password for the `operator` user on the PostgreSQL database using the `get-password` action:

```bash
juju run postgresql/leader get-password
```

As a result, you should see output similar to the following:

```text
...
password: bQOUgw8ZZgUyPA6n
```

Make note of the password, and use `juju ssh` to connect to the PostgreSQL unit:

```bash
juju ssh postgresql/leader
```

Once connected to the unit, use the `psql` command line tool with the `operator` user credentials, to create the database named `tutorial`:

```bash
psql --host $(hostname -i) --username operator --password --dbname postgres \
    -c "CREATE DATABASE tutorial"
```

You will be prompted to type the password, which you have obtained previously.

Now, we can use the `populate.sql` script copied earlier into the PostgreSQL unit, to create a table named `posts` with some test data:

```bash
cat populate.sql | \
    psql --host $(hostname -i) --username operator --password --dbname tutorial
```

To ensure that the test data is loaded successfully into the `posts` table, use the following command:

```bash
psql --host $(hostname -i) --username operator --password --dbname tutorial \
    -c 'SELECT COUNT(*) FROM posts'
```

The output should indicate that the `posts` table has five rows now: 

```text
 count 
-------
     5
(1 row)
```

Log out from the PostgreSQL unit using `exit` command or the `Ctrl+D` keyboard shortcut.

### Deploy and integrate the `postgresql-connect-integrator` charm

Now that you have sample data loaded into PostgreSQL, it is time to deploy the `postgresql-connect-integrator` charm to enable integration of PostgreSQL and Kafka Connect applications. 
First, deploy the charm in `source` mode using the `juju deploy` command and provide the minimum necessary configurations:

```bash
juju deploy postgresql-connect-integrator \
    --channel edge \
    --config mode=source \
    --config db_name=tutorial \
    --config topic_prefix=etl_
```

Each Kafka Connect integrator application needs at least two relations: 

* with the Kafka Connect 
* with a Database charm (e.g. MySQL, PostgreSQL, OpenSearch, etc.)

Integrate both Kafka Connect and PostgreSQL with the `postgresql-connect-integrator` charm:

```bash
juju integrate postgresql-connect-integrator postgresql
juju integrate postgresql-connect-integrator kafka-connect
```

After a couple of minutes, `juju status` command should show the `postgresql-connect-integrator` in `active|idle` state, with a message indicating that the ETL task is running:

```text
...
postgresql-connect-integrator/0*  active    idle   13       10.38.169.83    8080/tcp  Task Status: RUNNING
...
```

This means that the integrator application is actively copying data from the source database (named `tutorial`) into Apache Kafka topics prefixed with `etl_`. 
For example, rows in the `posts` table will be published into the Apache Kafka topic named `etl_posts`.

### Deploy and integrate the `opensearch-connect-integrator` charm

You are almost done with the ETL task, the only remaining part is to move data from Apache Kafka to OpenSearch. 
To do that, deploy another Kafka Connect integrator named `opensearch-connect-integrator` in the `sink` mode:

```bash
juju deploy opensearch-connect-integrator \
    --channel edge \
    --config mode=sink \
    --config topics="etl_posts"
```

The above command deploys an integrator application to move messages from the `etl_posts` topic to the index in OpenSearch named `etl_posts`. 
And the `etl_posts` topic is filled by the `postgresql-connect-integrator` charm we deployed earlier.

To activate the `opensearch-connect-integrator`, make the necessary integrations:

```bash
juju integrate opensearch-connect-integrator opensearch
juju integrate opensearch-connect-integrator kafka-connect
```

Wait a couple of minutes and run `juju status`, now both `opensearch-connect-integrator` and `postgresql-connect-integrator` applications should be in `active|idle` state, showing a message indicating that the ETL task is running:

```text
...
opensearch-connect-integrator/0*  active    idle   14       10.38.169.108   8080/tcp  Task Status: RUNNING
postgresql-connect-integrator/0*  active    idle   13       10.38.169.83    8080/tcp  Task Status: RUNNING
...
```

### Verify data transfer

Now it's time to verify that the data is being copied from the PostgreSQL database to the OpenSearch index. 
We can use the OpenSearch REST API for that purpose.

First, retrieve the admin user credentials for OpenSearch using `get-password` action:

```bash
juju run opensearch/leader get-password
```

As a result, you should see output similar to the following:

```text
...
password: GoCNE5KdFywT4nF1GSrwpAGyqRLecSXC
username: admin
```

Then, retrieve the OpenSearch unit IP and save it into an environment variable:

```bash
OPENSEARCH_IP=$(juju ssh opensearch/0 'hostname -i')
```

Now, using the password obtained above, send a request to the topic's `_search` endpoint, either using your browser or `curl`:

```bash
curl -u admin:<admin-password> -k -X GET https://$OPENSEARCH_IP:9200/etl_posts/_search
```

As a result you get a JSON response containing the search results, which should have five documents. 
The `hits.total` value should be `5`, as shown in the output example below:

```text
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

Now let's insert a new post into the PostgreSQL database. First SSH in to the PostgreSQL leader unit:

```bash
juju ssh postgresql/leader
```

Then, insert a new post using following command and the password for the `operator` user on the PostgreSQL:

```bash
psql --host $(hostname -i) --username operator --password --dbname tutorial -c \ 
    "INSERT INTO posts (content, likes) VALUES ('my new post', 1)"
```

Log out from the PostgreSQL unit using `exit` command or the `Ctrl+D` keyboard shortcut.

Then, check that the data is automatically copied to the OpenSearch index:

```bash
curl -u admin:<admin-password> -k -X GET https://$OPENSEARCH_IP:9200/etl_posts/_search
```

Which now should have six hits (output is truncated):

```text
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

Congratulations! You have successfully completed an ETL job that continuously moves data from PostgreSQL to OpenSearch, using entirely charmed solutions.

