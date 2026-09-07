resource "juju_application" "connect" {
  model_uuid = var.model_uuid
  name       = var.app_name

  charm {
    name     = "kafka-connect"
    channel  = var.channel
    revision = var.revision
    base     = var.base
  }

  units       = length(var.machines) == 0 ? var.units : null
  machines    = length(var.machines) > 0 ? var.machines : null
  constraints = var.constraints
  config      = var.config
}

resource "juju_offer" "connect_client" {
  model_uuid       = var.model_uuid
  application_name = juju_application.connect.name
  endpoints        = ["connect-client"]
}