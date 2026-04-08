terraform {
  required_version = ">= 1.5"
  required_providers {
    juju = {
      source  = "juju/juju"
      version = "~> 1.0"
    }
  }
}

provider "juju" {}

# variables
variable "model" {
  description = "tracing setup juju model. Defaults to `tracing`."
  type        = string
  default     = "tracing"
}


resource "juju_model" "dev" {
  name = var.model
}

# tempo cluster
resource "juju_application" "tempo_coordinator" {
  name       = "tempo"
  model_uuid = juju_model.dev.id
  trust      = true
  units      = 1

  charm {
    name    = "tempo-coordinator-k8s"
    channel = "2/edge"
  }
}

resource "juju_application" "tempo_worker" {
  name       = "tempo-worker"
  model_uuid = juju_model.dev.id
  trust      = true
  units      = 1

  charm {
    name    = "tempo-worker-k8s"
    channel = "2/edge"
  }
}

resource "juju_application" "tempo_s3" {
  name       = "tempo-s3"
  model_uuid = juju_model.dev.id
  trust      = true
  units      = 1

  charm {
    name    = "seaweedfs-k8s"
    channel = "latest/edge"
  }
}

resource "juju_integration" "coordinator_to_s3" {
  model_uuid = juju_model.dev.id

  application {
    name     = juju_application.tempo_s3.name
    endpoint = "s3-credentials"
  }

  application {
    name     = juju_application.tempo_coordinator.name
    endpoint = "s3"
  }
}

resource "juju_integration" "coordinator_to_worker" {
  model_uuid = juju_model.dev.id

  application {
    name     = juju_application.tempo_coordinator.name
    endpoint = "tempo-cluster"
  }

  application {
    name     = juju_application.tempo_worker.name
    endpoint = "tempo-cluster"
  }
}

# grafana
resource "juju_application" "grafana" {
  name       = "grafana"
  model_uuid = juju_model.dev.id
  trust      = true
  units      = 1

  charm {
    name    = "grafana-k8s"
    channel = "2/edge"
  }
}

# traefik
resource "juju_application" "traefik" {
  name       = "traefik"
  model_uuid = juju_model.dev.id
  trust      = true
  units      = 1

  charm {
    name    = "traefik-k8s"
    channel = "latest/edge"
  }
}

# ingress relations (to accommodate for machine charms)
resource "juju_integration" "tempo_ingress" {

  model_uuid = juju_model.dev.id

  application {
    name     = juju_application.tempo_coordinator.name
    endpoint = "ingress"
  }

  application {
    name     = juju_application.traefik.name
    endpoint = "traefik-route"
  }
}

resource "juju_integration" "grafana_ingress" {

  model_uuid = juju_model.dev.id

  application {
    name     = juju_application.grafana.name
    endpoint = "ingress"
  }

  application {
    name     = juju_application.traefik.name
    endpoint = "traefik-route"
  }
}

# grafana source relations
resource "juju_integration" "grafana_source" {

  model_uuid = juju_model.dev.id

  application {
    name     = juju_application.tempo_coordinator.name
    endpoint = "grafana-source"
  }

  application {
    name     = juju_application.grafana.name
    endpoint = "grafana-source"
  }
}
