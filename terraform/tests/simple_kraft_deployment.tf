module "kafka" {
  source     = "../"
  app_name   = var.app_name
  model = var.model_name
  units      = var.simple_kraft_kafka_units

  config = {
    roles="broker,controller"
    profile="testing"
  }

  channel = "3/edge"
}

resource "null_resource" "simple_kraft_deployment_juju_wait_deployment" {
  provisioner "local-exec" {
    command = <<-EOT
    juju-wait -v --model ${var.model_name}
    EOT
  }

  depends_on = [juju_integration.simple_deployment_tls-operator_opensearch-integration]
}