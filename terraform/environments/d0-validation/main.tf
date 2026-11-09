variable "enabled" {
  type        = bool
  default     = false
  description = "Explicit installation opt-in. Default creates nothing."
}

variable "runtime_enabled" {
  type        = bool
  default     = false
  description = "Enable runtime OIDC only after separate installation verification."
}

variable "configuration" {
  type = object({
    account_id                   = string
    image_uri                    = string
    bootstrap_execution_role_arn = string
    master_secret_arn            = string
    installation_log_group       = string
    db_host                      = string
    db_name                      = string
    subnet_ids                   = list(string)
    security_group_ids           = list(string)
  })
  default = null
}

module "d0" {
  count           = var.enabled ? 1 : 0
  source          = "../../modules/d0-validation"
  configuration   = var.configuration
  runtime_enabled = var.runtime_enabled
}

output "installation" { value = try(module.d0[0].installation, null) }
output "runtime" { value = try(module.d0[0].runtime, null) }
