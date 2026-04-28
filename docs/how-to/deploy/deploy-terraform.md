---
myst:
  html_meta:
    description: "Deploy Charmed Apache Kafka using Terraform and the Juju Terraform provider."
---

(how-to-deploy-terraform)=
# How to deploy via Terraform

This guide describes how to deploy Charmed Apache Kafka using [Terraform](https://www.terraform.io/) and the [Juju Terraform provider](https://registry.terraform.io/providers/juju/juju/latest/docs).

For Juju CLI-based deployment, see the [Juju CLI deployment guide](how-to-deploy-anywhere).

## Prerequisites

* A Juju controller bootstrapped on a **non-Kubernetes** cloud (see [Juju CLI deployment guide](how-to-deploy-anywhere) for setup instructions)
* A Juju model created on the controller
* [Terraform](https://developer.hashicorp.com/terraform/install) (`>= 1.0.0`) installed

## Terraform configuration

Save the following as `main.tf` in a new working directory. The module is sourced from the [`terraform/` directory](https://github.com/canonical/kafka-bundle/tree/main/terraform) in the Charmed Apache Kafka bundle repository.

The same `main.tf` is used for both production and testing deployments — the deployment mode is controlled via a `kafka.auto.tfvars` file.

<details>

<summary>See main.tf</summary>

```hcl
terraform {
  required_providers {
    juju = {
      source  = "juju/juju"
      version = ">= 1.0.0"
    }
  }
}

provider "juju" {}

variable "model_name" {
  description = "Name of the Juju model to deploy to"
  type        = string
}

variable "model_owner" {
  description = "Owner of the Juju model"
  type        = string
  default     = "admin"
}

variable "profile" {
  description = "Deployment profile: 'production' or 'testing'"
  type        = string
  default     = "testing"
}

variable "broker" {
  description = "Apache Kafka broker configuration"
  default     = {}
}

variable "controller" {
  description = "Apache Kafka KRaft controller configuration"
  default     = {}
}

variable "integrator" {
  description = "Data Integrator configuration for admin user creation"
  default     = { units = 0 }
}

variable "connect" {
  description = "Kafka Connect configuration"
  default     = { units = 0 }
}

variable "karapace" {
  description = "Karapace Schema Registry configuration"
  default     = { units = 0 }
}

variable "ui" {
  description = "Kafbat Kafka UI configuration"
  default     = { units = 0 }
}

variable "tls_offer" {
  description = "TLS provider cross-model offer URL"
  type        = string
  default     = null
}

variable "cos_offers" {
  description = "COS cross-model offer URLs for observability"
  default     = {}
}

data "juju_model" "kafka" {
  name  = var.model_name
  owner = var.model_owner
}

module "kafka" {
  source = "git::https://github.com/canonical/kafka-bundle//terraform?ref=main"

  model_uuid = data.juju_model.kafka.uuid
  profile    = var.profile
  broker     = var.broker
  controller = var.controller
  integrator = var.integrator
  connect    = var.connect
  karapace   = var.karapace
  ui         = var.ui
  tls_offer  = var.tls_offer
  cos_offers = var.cos_offers
}
```

</details>

When `controller` includes `units > 0`, the module deploys separate broker and controller applications. When `controller` is omitted or has `units = 0` (the default), the broker co-locates both the broker and controller roles in a single application.

## Deploy for production

For production use, deploy separate `kafka` (broker) and `controller` (KRaft controller) applications and integrate them. To maintain high availability, 3+ broker units and 3 or 5 controller units are recommended.

Save the following as `kafka.auto.tfvars`:

```hcl
model_name = "terraform"
profile    = "production"

broker = {
  app_name = "kafka"
  channel  = "4/stable"
  units    = 3
}

controller = {
  app_name = "controller"
  channel  = "4/stable"
  units    = 3
}
```

## (Alternative) Deploy for testing

For non-production testing clusters, co-locate both KRaft controller and broker services in a single application to save resources.

Alternatively, save the following as `kafka.auto.tfvars`:

```hcl
model_name = "terraform"

broker = {
  app_name = "kafka"
  channel  = "4/stable"
  units    = 3
}
```

Since `controller` is omitted, the module defaults to zero controller units and co-locates the controller role within the broker application. The `profile` defaults to `"testing"`.

## Deploy

Initialise Terraform, then preview and apply the deployment:

```shell
terraform init
terraform plan
```

Review the plan output, then apply:

```shell
terraform apply
```

Terraform automatically loads the `.auto.tfvars` file in the working directory. See [profile reference](https://charmhub.io/kafka/configurations?channel=4/stable#profile).

Wait for Terraform to finish.
Then, monitor the Juju model status with:

```shell
watch juju status --color
```

The deployment is complete once all units show `active` and `idle` status.

## (Optional) Create an external admin user

After deployment, the Apache Kafka cluster does not expose any external listeners by default. To create an admin user, add the following `integrator` block to your `kafka.auto.tfvars` file:

```hcl
integrator = {
  app_name = "data-integrator"
  channel  = "latest/stable"
  config   = {
    topic-name       = "__admin-user"
    extra-user-roles = "admin"
  }
  units = 1
}
```

The Data Integrator is configured with `admin` role, granting `super.user` permissions on the cluster. The bundle automatically integrates it with the Kafka broker.

Apply the changes:

```shell
terraform apply
```

Retrieve authentication credentials with:

```shell
juju run data-integrator/leader get-credentials
```

## (Optional) Enable TLS encryption

To encrypt client-facing traffic, pass a [cross-model offer](https://documentation.ubuntu.com/juju/latest/reference/relation/#cross-model-relation) URL from an existing TLS provider (e.g. `self-signed-certificates`) to the module. Add the following to your `kafka.auto.tfvars` file:

```hcl
tls_offer = "<controller>:<owner>/<model>.certificates"
```

The module will integrate all Kafka applications with the TLS provider automatically.

## (Optional) Enable observability with COS

To connect the cluster to the [Canonical Observability Stack (COS)](https://documentation.ubuntu.com/observability/), provide the three required cross-model offer URLs. Add the following to your `kafka.auto.tfvars` file:

```hcl
cos_offers = {
  dashboard = "<controller>:<owner>/<cos-model>.grafana-dashboards"
  metrics   = "<controller>:<owner>/<cos-model>.prometheus-scrape"
  logging   = "<controller>:<owner>/<cos-model>.loki-logging"
}
```

All three fields must be set together — the module validates that either all or none are provided.

## Terraform module reference

See the [Terraform module reference](reference-terraform) for the full list of input variables and outputs exposed by the Charmed Apache Kafka Terraform module.
