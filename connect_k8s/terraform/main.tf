resource "juju_application" "connect" {
  model_uuid = var.model_uuid
  name       = var.app_name

  charm {
    name     = "kafka-connect-k8s"
    channel  = var.channel
    revision = var.revision
    base     = var.base
  }

  units       = var.units
  constraints = var.constraints
  config      = var.config
  trust       = true
}

resource "juju_offer" "connect_client" {
  model_uuid       = var.model_uuid
  application_name = juju_application.connect.name
  endpoints        = ["connect-client"]
}
