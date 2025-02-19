# Manage message schemas

Follow the first steps of the [How to deploy Charmed Apache Kafka](https://discourse.charmhub.io/t/charmed-kafka-documentation-how-to-deploy/13261) guide to set up the environment. Stop before deploying Charmed Apache Kafka and continue with the instructions below.

## Setting up Karapace

Karapace is a drop-in replacement, open-source implementation of Confluent's Schema Registry, and supports the storing of schemas in a central repository, which clients can access to serialize and deserialize messages written to Apache Kafka.

To deploy Karapace and integrate it with Apache Kafka, use the following commands:

```bash
$ juju deploy karapace --channel latest/edge
$ juju integrate karapace kafka
```

Once deployed, the password to access the Karapace REST API can be obtained:

```shell
juju run karapace/leader get-password username="operator"
```

With this password, list all registered schemas using:

```bash
curl -u operator:<password> -X GET http://<karapace-unit-ip>:8081/subjects
```

## Registering new schemas

To register the first version of a schema named `house-pets` with fields `animal` and `age` using Avro schema, run:

```bash
curl -u operator:<password> -X POST -H "Content-Type: application/vnd.schemaregistry.v1+json" \
     http://<karapace-unit-ip>:8081/subjects/house-pets/versions \
    --data '{"schema": "{\"type\": \"record\", \"name\": \"Obj\", \"fields\":[{\"name\": \"animal\", \"type\": \"string\"},{\"name\": \"age\", \"type\": \"int\"}]}"}'
```

If successful, this should result in an output showing the global ID for this new schema:

```bash
{"id":1}
```

To register a version of the same schema above using JSON schema to a different subject with name `house-pets-json`, run:

```bash
curl -u operator:<password> -X POST -H "Content-Type: application/vnd.schemaregistry.v1+json" \
    http://<karapace-unit-ip>:8081/subjects/house-pets-json/versions \
    --data '{"schemaType": "JSON", "schema": "{\"type\": \"object\",\"properties\":{\"animal\":{\"type\": \"string\"}, \"age\":{\"type\": \"number\"}},\"additionalProperties\":true}"}'
```

If successful, this should result in output:

```bash
{"id":2}
```

## Adding new schema versions

To test the compatibility of a schema with the latest schema version, for example `house-pets` schema with a field changed, run:

```bash
curl -u operator:<password> -X POST -H "Content-Type: application/vnd.schemaregistry.v1+json" \
     http://<karapace-unit-ip>:8081/subjects/house-pets/versions/latest \
    --data '{"schema": "{\"type\": \"record\", \"name\": \"Obj\", \"fields\":[{\"name\": \"animal\", \"type\": \"string\"}]}"}'
```

If compatible, this will result in output:

```bash
{"is_compatible":true}
```

To register a new schema version, for example the above compatible schema, run:

```bash
curl -u operator:<password> -X POST -H "Content-Type: application/vnd.schemaregistry.v1+json" \
     http://<karapace-unit-ip>:8081/subjects/house-pets/versions \
    --data '{"schema": "{\"type\": \"record\", \"name\": \"Obj\", \"fields\":[{\"name\": \"animal\", \"type\": \"string\"}]}"}'
```

## Deleting schema versions

In order to delete a specific schema version, for example version 1 of the `house-pets` schema, run:

```bash
curl -u operator:<password> -X DELETE http://<karapace-unit-ip>:8081/subjects/house-pets/versions/1
```

To delete all versions of the schema, for example `house-pets-json`, run:

```bash
curl -u operator:<password> -X DELETE http://<karapace-unit-ip>:8081/subjects/house-pets-json
```
