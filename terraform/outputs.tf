# CC006 mandatory outputs
output "app_name" {
  description = "Name of the main Kafka application"
  value       = juju_application.kafka.name
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
    kafka-client = juju_offer.kafka_client.url
  }
}

output "kafka_client_offer" {
  description = "Kafka client offer URL for external applications"
  value       = juju_offer.kafka_client.url
}
