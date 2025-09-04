# CC006 mandatory inputs
variable "app_name" {
  description = "Name of the Juju application"
  type        = string
}

variable "channel" {
  description = "Charm channel to deploy from"
  type        = string
  default = "4/edge"
}

variable "config" {
  description = "Application configuration"
  type        = map(string)
  default     = {}
}

variable "constraints" {
  description = "Juju constraints for the application"
  type        = string
  default     = "arch=amd64"
}

variable "model" {
  description = "Juju model to deploy to"
  type        = string
}

variable "revision" {
  description = "Charm revision to deploy"
  type        = number
  default     = null
}

variable "units" {
  description = "Number of units to deploy"
  type        = number
  default     = 3
}

variable "storage" {
  description = "Map of storage used by the application"
  type        = map(string)
  default     = {}
}

# Additional inputs
variable "base" {
  description = "Application base"
  type        = string
  default     = "ubuntu@24.04"
}

variable "deployment_mode" {
  description = "Kafka deployment mode: 'single' (combined broker+controller) or 'split' (separate broker and controller)"
  type        = string
  default     = "split"
  
  validation {
    condition     = contains(["single", "split"], var.deployment_mode)
    error_message = "Deployment mode must be either 'single' or 'split'."
  }
}

variable "broker_units" {
  description = "Number of broker units (used in split mode or overrides units in single mode)"
  type        = number
  default     = null
}

variable "controller_units" {
  description = "Number of controller units (only used in split mode)"
  type        = number
  default     = 3
}

variable "broker_app_name" {
  description = "Name for the broker application in split mode (defaults to app_name-broker)"
  type        = string
  default     = null
}

variable "controller_app_name" {
  description = "Name for the controller application in split mode (defaults to app_name-controller)"
  type        = string
  default     = null
}
