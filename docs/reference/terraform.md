---
myst:
  html_meta:
    description: "Reference for the Charmed Apache Kafka Terraform module - input variables and outputs."
---

(reference-terraform)=
# Terraform module reference

Reference for the [Charmed Apache Kafka Terraform module](https://github.com/canonical/kafka-operator/tree/main/terraform), used with the [Juju Terraform provider](https://registry.terraform.io/providers/juju/juju/latest/docs).

See also: [How to deploy via Terraform](how-to-deploy-terraform).

## Input variables

| Variable | Type | Default | Description |
|---|---|---|---|
| `app_name` | `string` | (required) | Name of the Juju application |
| `model_uuid` | `string` | (required) | Juju model UUID to deploy to |
| `channel` | `string` | `"4/edge"` | Charm channel to deploy from |
| `units` | `number` | `3` | Number of units to deploy |
| `config` | `map(string)` | `{}` | Application configuration |
| `constraints` | `string` | `"arch=amd64"` | Juju constraints |
| `revision` | `number` | `null` | Charm revision to deploy |
| `base` | `string` | `"ubuntu@24.04"` | Application base |
| `storage` | `map(string)` | `{}` | Storage directives |
| `machines` | `set(string)` | `[]` | List of machine resources for deployment |

## Outputs

| Output | Description |
|---|---|
| `app_name` | Name of the deployed Kafka application |
| `provides_endpoints` | Relation endpoints this charm provides |
| `offers` | Cross-model offers created by this module |
| `kafka_client_offer` | Kafka client offer URL for external applications |
