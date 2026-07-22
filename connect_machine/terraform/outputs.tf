# CC006 mandatory outputs
output "app_name" {
  description = "Name of the Kafka Connect application"
  value       = juju_application.connect.name
}

output "endpoints" {
  description = "Service access endpoints"
  value = {
    # Add actual service URLs here if available
    # Could include REST API endpoints, etc.
  }
}

output "provides_endpoints" {
  description = "Relation endpoints this charm provides"
  value = [
    "connect-client",
    "cos-agent",
    "certificates"
  ]
}

output "offers" {
  description = "offers created by this charm"
  value = {
    connect-client = juju_offer.connect_client.url
  }
}

output "connect_client_offer" {
  description = "Kafka Connect client offer URL for external applications (deprecated - use offers output)"
  value       = juju_offer.connect_client.url
}