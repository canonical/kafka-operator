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

## Deploy for production

For production use, deploy separate `kafka` (broker) and `controller` (KRaft controller) applications and integrate them. To maintain high availability, 3+ broker units and 3 or 5 controller units are recommended.

<details>

<summary>Terraform configuration for production</summary>

Save the following as `main.tf` in a new working directory. The module is sourced directly from the [`terraform/` directory](https://github.com/canonical/kafka-operator/tree/main/terraform) in the Charmed Apache Kafka GitHub repository.

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

data "juju_model" "kafka" {
  name  = var.model_name
  owner = var.model_owner
}

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
  model_uuid = data.juju_model.kafka.uuid

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

</details>

## (Alternative) Deploy for testing

For non-production testing clusters, co-locate both KRaft controller and broker services in a single application to save resources.

<details>

<summary>Terraform configuration for testing</summary>

```{warning}
This is not recommended for production deployments. Apache Kafka brokers rely on the KRaft controllers to coordinate. If both services go down at the same time, the risk of cluster instability increases.
```

Save the following as `main.tf` in a new working directory:

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

data "juju_model" "kafka" {
  name  = var.model_name
  owner = var.model_owner
}

module "kafka" {
  source = "git::https://github.com/canonical/kafka-operator//terraform?ref=main"

  app_name   = "kafka"
  model_uuid = data.juju_model.kafka.uuid
  channel    = "4/stable"
  units      = 3
  config     = { roles = "broker,controller" }
}
```

</details>

## Deploy

Initialise Terraform, then preview and apply the deployment:

```shell
terraform init
terraform plan -var "model_name=<model-name>"
```

Review the plan output, then apply:

```shell
terraform apply -var "model_name=<model-name>"
```

Wait for the Terraform to finish.
Then, monitor the Juju model status with:

```shell
watch juju status --color
```

The deployment is complete once all units show `active` and `idle` status.

## (Optional) Create an external admin user

After deployment, the Apache Kafka cluster does not expose any external listeners by default. To create an admin user, deploy the [Data Integrator charm](https://charmhub.io/data-integrator).

<details>

<summary>Terraform configuration for admin user</summary>

Add the following resources to `main.tf`. The Data Integrator is configured with `admin` role, granting `super.user` permissions on the cluster.

```hcl
resource "juju_application" "data_integrator" {
  model_uuid = data.juju_model.kafka.uuid
  name       = "data-integrator"

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
  model_uuid = data.juju_model.kafka.uuid

  application {
    name = module.kafka.app_name
  }

  application {
    name = juju_application.data_integrator.name
  }
}
```

</details>

Apply the changes:

```shell
terraform apply -var "model_name=<model-name>"
```

Retrieve authentication credentials with:

```shell
juju run data-integrator/leader get-credentials
```

## Terraform module reference

See the [Terraform module reference](reference-terraform) for the full list of input variables and outputs exposed by the Charmed Apache Kafka Terraform module.
