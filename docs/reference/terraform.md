---
myst:
  html_meta:
    description: "Reference for the Charmed Apache Kafka Terraform module - input variables and outputs."
---

(reference-terraform)=
# Terraform module reference

Reference for the [VM Terraform module](https://github.com/canonical/kafka-bundle/tree/main/terraform)
and [K8s Terraform module](https://github.com/canonical/kafka-k8s-bundle/tree/main/terraform),
used with the [Juju Terraform provider](https://registry.terraform.io/providers/juju/juju/latest/docs).

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
| `ingress_offer` | `string` | `null` | Kubernetes: ingress provider endpoint for Kafka UI |
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
| `base` | `string` | Application base (default: `"ubuntu@24.04"`; dependent charms can define their own defaults) |
| `units` | `number` | Number of units to deploy |
| `storage` | `map(string)` | Storage directives (broker and controller only) |
| `machines` | `set(string)` | Machine: list of machine resources for deployment |

All fields are optional — defaults are set per application. Note that some
defaults differ between the VM and K8s modules (for example, `controller.units`
defaults to `0` on VM but `3` on K8s, and the default `channel` is `4/edge`).
See the
[VM source](https://github.com/canonical/kafka-bundle/tree/main/terraform) or
[K8s source](https://github.com/canonical/kafka-k8s-bundle/tree/main/terraform)
for the exact inputs and defaults.

## Outputs

| Output | Description |
|---|---|
| `app_names` | Map of all deployed application names |
| `offers` | Map of cross-model offer URLs (`kafka-client`, `connect-client`, `karapace-client`) |
