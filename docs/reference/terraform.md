---
myst:
  html_meta:
    description: "Reference for the Charmed Apache Kafka Terraform module - input variables and outputs."
---

(reference-terraform)=
# Terraform module reference

Reference for the [Charmed Apache Kafka Terraform module](https://github.com/canonical/kafka-bundle/tree/main/terraform), used with the [Juju Terraform provider](https://registry.terraform.io/providers/juju/juju/latest/docs).

See also: [How to deploy via Terraform](how-to-deploy-terraform).

## Input variables

| Variable | Type | Default | Description |
|---|---|---|---|
| `model_uuid` | `string` | (required) | Juju model UUID to deploy to |
| `profile` | `string` | `"testing"` | Deployment profile: `"production"` or `"testing"` |
| `broker` | `object` | `{}` | Apache Kafka broker application configuration |
| `controller` | `object` | `{}` | Apache Kafka KRaft controller application configuration |
| `integrator` | `object` | `{}` | Data Integrator application configuration |
| `connect` | `object` | `{}` | Kafka Connect application configuration |
| `karapace` | `object` | `{}` | Karapace Schema Registry application configuration |
| `ui` | `object` | `{}` | Kafbat Kafka UI application configuration |
| `tls_offer` | `string` | `null` | TLS provider endpoint for client relations |
| `cos_offers` | `object` | `{}` | COS offers for observability (`dashboard`, `metrics`, `logging`, `tracing`) |

### Application configuration objects

The `broker`, `controller`, `connect`, `karapace`, `ui`, and `integrator` variables accept objects with the following fields:

| Field | Type | Description |
|---|---|---|
| `app_name` | `string` | Name of the Juju application |
| `channel` | `string` | Charm channel to deploy from |
| `config` | `map(string)` | Application configuration |
| `constraints` | `string` | Juju constraints (default: `"arch=amd64"`) |
| `resources` | `map(string)` | Charm resources |
| `revision` | `number` | Charm revision to deploy |
| `base` | `string` | Application base (default: `"ubuntu@24.04"`) |
| `units` | `number` | Number of units to deploy |
| `storage` | `map(string)` | Storage directives (broker and controller only) |
| `machines` | `set(string)` | List of machine resources for deployment |

All fields are optional — defaults are set per application. See the [module source](https://github.com/canonical/kafka-bundle/tree/main/terraform) for the full list of defaults.

## Outputs

| Output | Description |
|---|---|
| `app_names` | Map of all deployed application names |
| `offers` | Map of cross-model offer URLs (`kafka-client`, `connect-client`, `karapace-client`) |
