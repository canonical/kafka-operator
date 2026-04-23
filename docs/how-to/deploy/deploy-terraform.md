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

## Configure the Terraform module

Create a Terraform working directory and a `main.tf` file with the following content:

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

data "juju_model" "kafka" {
  name = var.model_name
}
```

### Deploy for production

For production use, deploy separate broker and controller applications.

Add the following to `main.tf`:

```hcl
module "kafka" {
  source = "git::https://github.com/canonical/kafka-operator//terraform?ref=main"

  app_name   = "kafka"
  model_uuid = data.juju_model.kafka.uuid
  channel    = "4/stable"
  units      = 3
  config     = { roles = "broker" }
}

module "controller" {
  source = "git::https://github.com/canonical/kafka-operator//terraform?ref=main"

  app_name   = "controller"
  model_uuid = data.juju_model.kafka.uuid
  channel    = "4/stable"
  units      = 3
  config     = { roles = "controller" }
}

resource "juju_integration" "peer_cluster" {
  model = var.model_name

  application {
    name     = module.kafka.app_name
    endpoint = "peer-cluster-orchestrator"
  }

  application {
    name     = module.controller.app_name
    endpoint = "peer-cluster"
  }
}
```

### (Alternative) Deploy for testing

For non-production testing clusters, co-locate both KRaft controller and broker services in a single application:

```{warning}
This is not recommended for production deployments. Apache Kafka brokers rely on the KRaft controllers to coordinate. If both services go down at the same time, the risk of cluster instability increases.
```

```hcl
module "kafka" {
  source = "git::https://github.com/canonical/kafka-operator//terraform?ref=main"

  app_name   = "kafka"
  model_uuid = data.juju_model.kafka.uuid
  channel    = "4/stable"
  units      = 3
  config     = { roles = "broker,controller" }
}
```

### Define variables

Create a `variables.tf` file:

```hcl
variable "model_name" {
  description = "Name of the Juju model to deploy to"
  type        = string
}
```

## Deploy

Initialise Terraform, then preview and apply the deployment:

```shell
terraform init
terraform plan -var "model_name=<your-model-name>"
```

Review the plan output, then apply:

```shell
terraform apply -var "model_name=<your-model-name>"
```

Wait for the deployment to settle. You can monitor the status with:

```shell
juju status --watch 5s
```

The deployment is complete once all units show `active` and `idle` status.

## (Optional) Create an external admin user

After deployment, the Apache Kafka cluster does not expose any external listeners by default. To create an admin user, deploy the [Data Integrator charm](https://charmhub.io/data-integrator).

Add the following to `main.tf`:

```hcl
resource "juju_application" "data_integrator" {
  model = var.model_name
  name  = "data-integrator"

  charm {
    name    = "data-integrator"
    channel = "latest/stable"
  }

  config = {
    topic-name       = "__admin-user"
    extra-user-roles = "admin"
  }

  units = 1
}

resource "juju_integration" "kafka_data_integrator" {
  model = var.model_name

  application {
    name = module.kafka.app_name
  }

  application {
    name = juju_application.data_integrator.name
  }
}
```

Apply the changes:

```shell
terraform apply -var "model_name=<your-model-name>"
```

Retrieve authentication credentials with:

```shell
juju run data-integrator/leader get-credentials
```

## Terraform module reference

The Charmed Apache Kafka Terraform module exposes the following variables:

| Variable | Type | Default | Description |
|---|---|---|---|
| `app_name` | `string` | (required) | Name of the Juju application |
| `channel` | `string` | `"4/edge"` | Charm channel to deploy from |
| `model_uuid` | `string` | (required) | Juju model UUID to deploy to |
| `units` | `number` | `3` | Number of units to deploy |
| `config` | `map(string)` | `{}` | Application configuration |
| `constraints` | `string` | `"arch=amd64"` | Juju constraints |
| `revision` | `number` | `null` | Charm revision to deploy |
| `base` | `string` | `"ubuntu@24.04"` | Application base |
| `storage` | `map(string)` | `{}` | Storage directives |
| `machines` | `set(string)` | `[]` | List of machine resources for deployment |
