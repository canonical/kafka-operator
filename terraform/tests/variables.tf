# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

variable "model_name" {
  description = "Model name"
  type        = string
}

variable "app_name" {
  description = "Kafka app name"
  type        = string
  default     = "kafka"
}

variable "simple_kraft_kafka_units" {
  description = "Node count"
  type        = number
  default     = 3
}