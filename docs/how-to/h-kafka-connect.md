# How to use Kafka Connect for ETL workloads

[Kafka Connect](https://kafka.apache.org/documentation/#connect) is a framework for easy deployment of Apache Kafka clients for common ETL tasks on different data sources and sinks, managed through multiple jobs running on a distributed cluster of workers.

The main concepts to understand before starting to work with Kafka Connect are:

- **Connectors**: The high level abstraction that coordinates data streaming by managing tasks.
- **Tasks**: The implementation of how data is copied to or from Apache Kafka.
- **Workers**: The running processes that execute connectors and tasks. Workers could be run either in `standalone` or `distributed` mode.
- **Converters**: The code used to translate data between Kafka Connect and the system sending or receiving data.
- **Transforms**: Simple logic to alter each message produced by or sent to a connector.

When a connector is first submitted to the Kafka Connect cluster, the workers rebalance work across the current connectors in the cluster. The workers can be configured to run in standalone or distributed mode, which utilize Apache Kafka topics to sync tasks across workers.

The **Charmed Kafka Connect Operator** delivers automated operations management from day 0 to day 2 on *Kafka Connect*, which hugely simplifies the deployment and adminisitrative tasks on Kafka Connect clusters

This operator can be found on [Charmhub](https://charmhub.io/kafka-connect) and it comes with production-ready features such as:

- Automated or manual connector plugins management.
- Fault-tolerance, replication and scalability out of the box.
- Authenticaon on REST API enabled by default.
- TLS support both on the REST API and Apache Kafka cluster relations.
- Seamless integration with Charmed Apache Kafka set of operators
- Seamless integration with an ecosystem of of Integrator charms supporting common ETL tasks on different database technologies offered by [Canonical Data Platform](https://canonical.com/data).

This how-to will address the process of deploying Kafka Connect, its integration with an Apache Kafka cluster and necessary steps to run a connector, either manually or by the means of an integrator charm.

## Prerequisites

Follow the steps of the [How to deploy Charmed Apache Kafka](https://discourse.charmhub.io/t/charmed-kafka-documentation-how-to-deploy/13261) guide to set up the environment. For this guide, we will need an active Charmed Apache Kafka application, either using Zookeeper or in KRaft mode.

## Deploy and set up Kafka Connect

To deploy Charmed Kafka Connect and integrate it with Charmed Apache Kafka, use the following commands:

```bash
juju deploy kafka-connect --channel latest/edge
juju integrate kafka-connect kafka
```

## Using Kafka Connect REST API 

Kafka Connect uses a RESTful interface to support common administrative tasks. Charmed Kafka Connect activates authentication by default on the Kafka Connect REST API. You should configure the password of the built-in `admin` user, using Juju secrets. The process is as follows:

First, create a secret in Juju containing your password:

```bash
juju add-secret mysecret admin=securepassword
```

You will get the secret-id as response. Make note of this, as you will need to configure it to the Kafka Connect charm soon:

```
secret:cvh7kruupa1s46bqvuig
```

Now, grant the secret to the Kafka Connect charm using `juju grant-secret` command:

```
juju grant-secret mysecret kafka-connect
```

As final step, Kafka Connect charm should be configured to use the provided secret. This could be done by issuing the `juju config` command, using the secret-id obtained above:

```bash
juju config kafka-connect admin_secret=secret:cvh7kruupa1s46bqvuig
```

To check that Kafka Connect is configured and works properly, make a request to the REST interface to list all registered connectors, using the password configured:

```bash
curl -u admin:securepassword -X GET http://<kafka-connect-unit-ip>:8083/connector-plugins
```

You should get a response like below:

```bash
[{"class":"org.apache.kafka.connect.mirror.MirrorCheckpointConnector","type":"source","version":"3.9.0-ubuntu1"},{"class":"org.apache.kafka.connect.mirror.MirrorHeartbeatConnector","type":"source","version":"3.9.0-ubuntu1"},{"class":"org.apache.kafka.connect.mirror.MirrorSourceConnector","type":"source","version":"3.9.0-ubuntu1"}]
```

## Adding a Connector Plugin

Kafka Connect uses a pluggable architecture model, meaning that the user could add desired functionalities by means of **Plugins**, also known as **Connectors**. Simply put, plugins are bundles of JAR files adhering to Kafka Connect Connector Interface. These connectors could be an implementation of a data source connector, data sink connector, a transformer or a converter. Kafka Connect automatically discovers added plugins, and the user could use the exposed REST interface to define desired ETL tasks based on available plugins.

In order to add a custom plugin to the Charmed Kafka Connect, you could use `juju attach-resource` command. As an example, let's add the Aiven's open source S3 source connector to Charmed Kafka Connect.

First, we should download the connector from the [respective repository](https://github.com/Aiven-Open/cloud-storage-connectors-for-apache-kafka). We will be using the `v3.2.0` release:

```bash
wget https://github.com/Aiven-Open/cloud-storage-connectors-for-apache-kafka/releases/download/v3.2.0/s3-source-connector-for-apache-kafka-3.2.0.tar
```

Once downloaded, attach the connector to the charm using `juju attach-resource` command.

```bash
juju attach-resource kafka-connect connect-plugin=./s3-source-connector-for-apache-kafka-3.2.0.tar
```

This would trigger a restart of Charmed Kafka Connect, once all units show as `active|idle`, your desired plugin is ready to use. This could be verified using the Connect REST API:

```bash
curl -u admin:securepassword -X GET http://<kafka-connect-unit-ip>:8083/connector-plugins
```

Which now should have `{"class":"io.aiven.kafka.connect.s3.source.S3SourceConnector","type":"source","version":"3.2.0"}` in its output.

## Manually Starting a Connector/Task

Once our desired plugin is available, we could use the Kafka Connect REST API to manually start a task. This would be achieved by POSTing a JSON containing task configuration to the `/connectors` endpoint. 

For example, in order to load data from `JSONL` files on an AWS S3 bucket named `testbucket` into a Apache Kafka topic named `s3topic`, the following request could be sent to the Kafka Connect REST endpoint (please refer to [Aiven's S3 source connector docs](https://github.com/Aiven-Open/cloud-storage-connectors-for-apache-kafka/tree/main/s3-source-connector#readme) for more details on connector configuration):

```bash
curl -u admin:securepassword \
     -H "Content-Type: application/json" \
     -d '{
          "name": "test-s3-source",
          "config": {
               "connector.class": "io.aiven.kafka.connect.s3.source.S3SourceConnector",
               "tasks.max": 1,
               "key.converter": "org.apache.kafka.connect.storage.StringConverter",
               "input.type": "jsonl",
               "topic": "s3topic",
               "aws.access.key.id": "<YOUR_AWS_KEY_ID>",
               "aws.secret.access.key": "<YOUR_AWS_SECRET_ACCESS_KEY>",
               "aws.s3.region": "us-east-1",
               "aws.s3.bucket.name": "testbucket"
          }
     }' -X POST http://<kafka-connect-unit-ip>:8083/connectors
```

> Please note that each connector comes with its own specific configuration options, and covering the specifics of each connector is beyond the scope of this document. Please consult the connector's documentation for more information on your use-case and whether or not the connector will support it.

## Manually Checking Connector/Task Status

Once the task has been submitted, we could query the `/connectors` REST endpoint to find out the status of our submitted connector/task:

```bash
curl -u admin:securepassword -X GET http://<kafka-connect-unit-ip>:8083/connectors?expand=status
```

The return value is a JSON showing status of each connector and its associated tasks:

```bash
{"test-s3-source":{"status":{"name":"test-s3-source","connector":{"state":"RUNNING","worker_id":"10.150.221.240:8083"},"tasks":[{"id":0,"state":"RUNNING","worker_id":"10.150.221.240:8083"}],"type":"source"}}}
```

## Stopping Connectors

The connector will be continuously running and moving data from the S3 source to Apache Kafka as long as the clusters are up. In order to stop the connector, we could use the `/connectors/<connector-name>/stop` endpoint:

```bash
curl -u admin:securepassword -X PUT http://<kafka-connect-unit-ip>:8083/connectors/test-s3-source/stop
```

If we check the connector status, it should now be in `STOPPED` state:

```bash
{"test-s3-source":{"status":{"name":"test-s3-source","connector":{"state":"STOPPED","worker_id":"10.150.221.240:8083"},"tasks":[],"type":"source"}}}
```

## Using Kafka Connect Integrator Charms

While connectors lifecycle management could be done manually using the Kafka Connect REST endpoint, for common use-cases such as moving data from/to popular databases/storage services, the recommended way is to use the Kafka Connect Integrator family of charms. 

Each integrator charm is designed for a generic ETL use-case, and aims to facilitate the end-to-end process of loading connector plugins, configuring the connector, starting and stopping the tasks, and reporting their status, thereby greatly simplifying the required administrative operations.

A curated set of integrators for common ETL use cases on [Canonical Data Platform line of products](https://canonical.com/data) are provided in the [Template Connect Integrator](https://github.com/canonical/template-connect-integrator) repository. These charmed operators support use cases such as loading data to and from MySQL, PostgreSQL, OpenSearch, S3-compatible storage services, and active/passive replication of Apache Kafka topics using MirrorMaker. To learn more about integrator charms, please refer to the tutorial which covers a practical use-case of moving data from MySQL to Opensearch using integrator charms.

