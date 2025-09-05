(how-to-schemas-serialisation)=
# Schemas and serialisation

Message schemas in Apache Kafka define the structure and format of data exchanged between producers and consumers. This guide provides instructions on managing schemas in Charmed Apache Kafka using Karapace. Karapace is a drop-in replacement, open-source implementation of Confluent's Schema Registry, and supports the storing of schemas in a central repository, which clients can access to serialise and deserialise messages written to Apache Kafka.

## Prerequisites

Follow the steps of the [How to deploy Charmed Apache Kafka](https://discourse.charmhub.io/t/charmed-kafka-documentation-how-to-deploy/13261) guide to set up the environment. For this guide, we will need an active Charmed Apache Kafka application, related to an active Charmed Apache ZooKeeper application.

## Deploy and set up Karapace

To deploy Karapace and integrate it with Apache Kafka, use the following commands:

```bash
juju deploy karapace --channel latest/edge
juju integrate karapace kafka
```

Once deployed, the password to access the Karapace REST API can be obtained:

```bash
juju run karapace/leader get-password username="operator"
```

To check that Karapace works correctly, list all registered schemas using the password from the previous command's output:

```bash
curl -u operator:<password> -X GET http://<karapace-unit-ip>:8081/subjects
```

## Registering a new schema

To register the first version of a schema `<schema-name>` with fields `<field1>` which is a string, and `<field2>` which is an integer using Avro schema, run:

```bash
curl -u operator:<password> -X POST -H "Content-Type: application/vnd.schemaregistry.v1+json" \
     http://<karapace-unit-ip>:8081/subjects/<schema-name>/versions \ --data '{"schema": "{\"type\": \"record\", \"name\": \"Obj\", \"fields\":[{\"name\": \"<field1>\", \"type\": \"string\"},{\"name\": \"<field2>\", \"type\": \"int\"}]}"}'
```

If successful, this should result in an output showing the global ID for this new schema:

```bash
{"id":1}
```

To register a version of the same schema above using JSON schema to a different subject with name `<schema-name-json>`, run:

```bash
curl -u operator:<password> -X POST -H "Content-Type: application/vnd.schemaregistry.v1+json" \
    http://<karapace-unit-ip>:8081/subjects/<schema-name-json>/versions \
    --data '{"schemaType": "JSON", "schema": "{\"type\": \"object\",\"properties\":{\"<field1>\":{\"type\": \"string\"}, \"<field2>\":{\"type\": \"number\"}},\"additionalProperties\":true}"}'
```

If successful, this should result in output:

```bash
{"id":2}
```

## Add new schema version

To test the compatibility of a schema with the latest schema version, for example `<schema-name>` schema with `<field2>` removed, run:

```bash
curl -u operator:<password> -X POST -H "Content-Type: application/vnd.schemaregistry.v1+json" \
     http://<karapace-unit-ip>:8081/subjects/<schema-name>/versions/latest \
    --data '{"schema": "{\"type\": \"record\", \"name\": \"Obj\", \"fields\":[{\"name\": \"<field1>\", \"type\": \"string\"}]}"}'
```

If compatible, this will result in output:

```bash
{"is_compatible":true}
```

To register a new schema version, run:

```bash
curl -u operator:<password> -X POST -H "Content-Type: application/vnd.schemaregistry.v1+json" \
     http://<karapace-unit-ip>:8081/subjects/<schema-name>/versions \
    --data '{"schema": "{\"type\": \"record\", \"name\": \"Obj\", \"fields\":[{\"name\": \"<field1>\", \"type\": \"string\"}]}"}'
```

## Delete schema version

To delete a specific schema version:

```bash
curl -u operator:<password> -X DELETE http://<karapace-unit-ip>:8081/subjects/<schema-name>/versions/<schema-version>
```

To delete all versions of a schema:

```bash
curl -u operator:<password> -X DELETE http://<karapace-unit-ip>:8081/subjects/<schema-name-json>
```

