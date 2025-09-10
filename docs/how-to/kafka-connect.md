(how-to-use-kafka-connect-for-etl-workloads)=
# How to use Kafka Connect for ETL workloads

[Kafka Connect](https://kafka.apache.org/documentation/#connect) is a framework for easy deployment of Apache Kafka clients for common ETL tasks on different data sources and sinks, managed through multiple jobs running on a distributed cluster of workers.

The Kafka Connect charm delivers automated operations management from day 0 to day 2 on *Kafka Connect*, which hugely simplifies the deployment and administrative tasks on Kafka Connect clusters.

This operator can be found on [Charmhub](https://charmhub.io/kafka-connect) and it comes with production-ready features such as automated and manual plugin management, replication and scalability, authentication, TLS support, and seamless integration with Charmed Apache Kafka set of operators.

This How-to guide covers deploying Kafka Connect, integrating it with Charmed Apache Kafka, and running a connector—either manually or using an integrator charm.

## Prerequisites

For this guide, we will need an active Charmed Apache Kafka application. Follow the [How to deploy Charmed Apache Kafka](https://discourse.charmhub.io/t/charmed-kafka-documentation-how-to-deploy/13261) guide to set up the environment.

## Deploy and set up

To deploy [Kafka Connect charm](https://charmhub.io/kafka-connect) and integrate it with Charmed Apache Kafka, use the following commands:

```bash
juju deploy kafka-connect --channel edge
juju integrate kafka-connect kafka
```

## Use REST API

Kafka Connect uses a RESTful API for common administrative tasks. By default, Charmed Kafka Connect enforces authentication on the Kafka Connect REST API.

To configure the password of the built-in `admin` user via Juju secrets, first, create a secret in Juju containing your password:

```bash
juju add-secret mysecret admin=<secure-password>
```

You will receive a secret-id in response. Make sure to note it down, as you will need to configure it for the Kafka Connect charm shortly. It looks like this:

```
secret:cvh7kruupa1s46bqvuig
```

Now, grant the secret to the Kafka Connect charm using `juju grant-secret` command:

```
juju grant-secret mysecret kafka-connect
```

Finally, the Kafka Connect charm should be configured to use the newly provided secret. This can be done by running the `juju config` command to specify the secret-id obtained above:

```bash
juju config kafka-connect system-users=secret:cvh7kruupa1s46bqvuig
```

To verify that Kafka Connect is properly configured and functioning, send a request to the REST interface to list all registered connectors using the password set in Juju secret:

```bash
curl -u admin:<secure-password> -X GET http://<kafka-connect-unit-ip>:8083/connector-plugins
```

You should get a response like below:

```bash
[
  {
    "class": "org.apache.kafka.connect.mirror.MirrorCheckpointConnector",
    "type": "source",
    "version": "3.9.0-ubuntu1"
  },
  {
    "class": "org.apache.kafka.connect.mirror.MirrorHeartbeatConnector",
    "type": "source",
    "version": "3.9.0-ubuntu1"
  },
  {
    "class": "org.apache.kafka.connect.mirror.MirrorSourceConnector",
    "type": "source",
    "version": "3.9.0-ubuntu1"
  }
]
```

## Add a connector plugin

To add a custom connector plugin to the Charmed Kafka Connect, you can use the `juju attach-resource` command. For example, let's add the Aiven's open source S3 source connector to Charmed Kafka Connect.

First, download the connector plugin `v3.2.0` from the [respective repository](https://github.com/Aiven-Open/cloud-storage-connectors-for-apache-kafka):

```bash
wget https://github.com/Aiven-Open/cloud-storage-connectors-for-apache-kafka/releases/download/v3.2.0/s3-source-connector-for-apache-kafka-3.2.0.tar
```

Once downloaded, attach the connector to the charm using the `juju attach-resource` command.

```bash
juju attach-resource kafka-connect connect-plugin=./s3-source-connector-for-apache-kafka-3.2.0.tar
```

This triggers a restart of Charmed Kafka Connect application. Once all units show `active|idle` status, the plugin is ready to use. To verify using the Kafka Connect REST API:

```bash
curl -u admin:<secure-password> -X GET http://<kafka-connect-unit-ip>:8083/connector-plugins
```

The output will have  `{"class":"io.aiven.kafka.connect.s3.source.S3SourceConnector","type":"source","version":"3.2.0"}`.

## Start connector/task

Once our desired plugin is available, use the Kafka Connect REST API to manually start a task. This can be achieved by sending a POST request with a JSON containing task configuration to the `/connectors` endpoint.

For example, in order to load data from `JSONL` files on an AWS S3 bucket named `testbucket` into a Apache Kafka topic named `s3topic`, the following request can be sent to the Kafka Connect REST endpoint (please refer to [Aiven's S3 source connector docs](https://github.com/Aiven-Open/cloud-storage-connectors-for-apache-kafka/tree/main/s3-source-connector#readme) for more details on the connector configuration):

```bash
curl -u admin:<secure-password> \
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

```{note}
Each connector has its own specific configuration options covering the specifics of each connector. Please refer to the connector's documentation for more information on available options and supported use cases.
```

## Check connector/task status

Once the task is submitted, we can query the `/connectors` REST endpoint to find out the status of our submitted connector/task:

```bash
curl -u admin:<secure-password> -X GET http://<kafka-connect-unit-ip>:8083/connectors?expand=status
```

The returned value is a JSON showing status of each connector and its associated tasks:

```bash
{
  "test-s3-source": {
    "status": {
      "name": "test-s3-source",
      "connector": {
        "state": "RUNNING",
        "worker_id": "10.150.221.240:8083"
      },
      "tasks": [
        {
          "id": 0,
          "state": "RUNNING",
          "worker_id": "10.150.221.240:8083"
        }
      ],
      "type": "source"
    }
  }
}
```

## Stop connector

A connector is continuously running as long as the cluster is up. To stop a connector, use the `/connectors/<connector-name>/stop` endpoint:

```bash
curl -u admin:<secure-password> -X PUT http://<kafka-connect-unit-ip>:8083/connectors/test-s3-source/stop
```

The connector is now in the `STOPPED` state:

```bash
{
  "test-s3-source": {
    "status": {
      "name": "test-s3-source",
      "connector": {
        "state": "STOPPED",
        "worker_id": "10.150.221.240:8083"
      },
      "tasks": [],
      "type": "source"
    }
  }
}
```

## Use Kafka Connect integrator charms

While connectors lifecycle management can be done manually using the Kafka Connect REST endpoint, for common use-cases such as moving data from/to popular databases/storage services, the recommended way is to use the Kafka Connect integrator family of charms.

Each integrator charm is designed for a general ETL use case and streamlines the entire process - from loading connector plugins to configuring connectors, managing task execution, and reporting status - significantly reducing administrative overhead.

A curated set of integrators for common ETL use cases on [Canonical Data Platform line of products](https://canonical.com/data) are provided in the [Template Connect Integrator](https://github.com/canonical/template-connect-integrator) repository.

These charmed operators support use cases such as loading data to and from MySQL, PostgreSQL, OpenSearch, S3-compatible storage services, and active/passive replication of Apache Kafka topics using MirrorMaker.

To learn more about integrator charms, please refer to the tutorial [Use Kafka Connect for ETL](tutorial-kafka-connect) which covers a practical use-case of moving data from MySQL to OpenSearch using integrator charms.
