# Single mode: Combined broker+controller
resource "juju_application" "kafka" {
  model_uuid = var.model_uuid
  name       = var.app_name

  charm {
    name     = "kafka"
    channel  = var.channel
    revision = var.revision
    base     = var.base
  }

  units       = var.units
  constraints = var.constraints
  config      = var.config

  storage_directives = var.storage

}

# Kafka client offer - Single mode
resource "juju_offer" "kafka_client" {
  model_uuid       = var.model_uuid
  application_name = juju_application.kafka.name
  endpoints        = ["kafka-client"]
}
