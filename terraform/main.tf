# Single mode: Combined broker+controller
resource "juju_application" "kafka_single" {
  count = var.deployment_mode == "single" ? 1 : 0
  model = var.model
  name  = var.app_name
  
  charm {
    name     = "kafka"
    channel  = var.channel
    revision = var.revision
    base     = var.base
  }

  units       = var.broker_units != null ? var.broker_units : var.units
  constraints = var.constraints
  config      = merge(var.config, {
    roles = "broker,controller"
  })
}

# Split mode: Separate controller
resource "juju_application" "kafka_controller" {
  count = var.deployment_mode == "split" ? 1 : 0
  model = var.model
  name  = var.controller_app_name != null ? var.controller_app_name : "${var.app_name}-controller"
  
  charm {
    name     = "kafka"
    channel  = var.channel
    revision = var.revision
    base     = var.base
  }
  
  units       = var.controller_units
  constraints = var.constraints
  config      = merge(var.config, {
    roles = "controller"
  })
}

# Split mode: Separate broker
resource "juju_application" "kafka_broker" {
  count = var.deployment_mode == "split" ? 1 : 0
  model = var.model
  name  = var.broker_app_name != null ? var.broker_app_name : "${var.app_name}-broker"
  
  charm {
    name     = "kafka"
    channel  = var.channel
    revision = var.revision
    base     = var.base
  }
  
  units       = var.broker_units != null ? var.broker_units : var.units
  constraints = var.constraints
  config      = merge(var.config, {
    roles = "broker"
  })
}

# Split mode: Integration between broker and controller
resource "juju_integration" "broker_controller" {
  count = var.deployment_mode == "split" ? 1 : 0
  model = var.model
  
  application {
    name     = juju_application.kafka_broker[0].name
    endpoint = "peer-cluster-orchestrator"
  }
  
  application {
    name     = juju_application.kafka_controller[0].name
    endpoint = "peer-cluster"
  }
}

# Kafka client offer - Single mode
resource "juju_offer" "kafka_client_single" {
  count            = var.deployment_mode == "single" ? 1 : 0
  model            = var.model
  application_name = juju_application.kafka_single[0].name
  endpoints        = ["kafka-client"]
}

# Kafka client offer - Split mode (broker provides client access)
resource "juju_offer" "kafka_client_split" {
  count            = var.deployment_mode == "split" ? 1 : 0
  model            = var.model
  application_name = juju_application.kafka_broker[0].name
  endpoints        = ["kafka-client"]
}