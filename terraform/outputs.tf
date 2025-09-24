# CC006 mandatory outputs
output "app_name" {
  description = "Name of the main Kafka application"
  value = var.deployment_mode == "single" ? (
    length(juju_application.kafka_single) > 0 ? juju_application.kafka_single[0].name : null
  ) : (
    length(juju_application.kafka_broker) > 0 ? juju_application.kafka_broker[0].name : null
  )
}

output "provides_endpoints" {
  description = "Relation endpoints this charm provides"
  value = [
    "kafka-client",
    "cos-agent",
  ]
}

output "offers" {
  description = "offers created by this charm"
  value = {
    kafka-client = var.deployment_mode == "single" ? (
      length(juju_offer.kafka_client_single) > 0 ? juju_offer.kafka_client_single[0].url : null
    ) : (
      length(juju_offer.kafka_client_split) > 0 ? juju_offer.kafka_client_split[0].url : null
    )
  }
}

# Additional outputs for reference
output "deployment_mode" {
  description = "Kafka deployment mode used"
  value       = var.deployment_mode
}

output "controller_app_name" {
  description = "Name of the controller application (split mode only)"
  value = var.deployment_mode == "split" ? (
    length(juju_application.kafka_controller) > 0 ? juju_application.kafka_controller[0].name : null
  ) : null
}

output "broker_app_name" {
  description = "Name of the broker application (split mode only)"
  value = var.deployment_mode == "split" ? (
    length(juju_application.kafka_broker) > 0 ? juju_application.kafka_broker[0].name : null
  ) : null
}

output "kafka_client_offer" {
  description = "Kafka client offer URL for external applications"
  value = var.deployment_mode == "single" ? (
    length(juju_offer.kafka_client_single) > 0 ? juju_offer.kafka_client_single[0].url : null
  ) : (
    length(juju_offer.kafka_client_split) > 0 ? juju_offer.kafka_client_split[0].url : null
  )
}
