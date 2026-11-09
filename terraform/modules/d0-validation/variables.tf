variable "configuration" {
  description = "Reviewed D0 metadata only. Secret values must never enter Terraform."
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
  validation {
    condition = (
      can(regex("^[0-9]{12}$", var.configuration.account_id)) &&
      can(regex(format("^%s[.]dkr[.]ecr[.]ap-northeast-2[.]amazonaws[.]com/ipgo-dev/database@sha256:[a-f0-9]{64}$", var.configuration.account_id), var.configuration.image_uri)) &&
      startswith(var.configuration.bootstrap_execution_role_arn, format("arn:aws:iam::%s:role/ipgo-dev-", var.configuration.account_id)) &&
      startswith(var.configuration.master_secret_arn, format("arn:aws:secretsmanager:ap-northeast-2:%s:secret:", var.configuration.account_id)) &&
      startswith(var.configuration.installation_log_group, "/ipgo/") &&
      can(regex("^[a-z0-9-]+[.][a-z0-9]+[.]ap-northeast-2[.]rds[.]amazonaws[.]com$", var.configuration.db_host)) &&
      can(regex("^[a-z][a-z0-9_]{0,62}$", var.configuration.db_name)) &&
      length(var.configuration.subnet_ids) > 0 && length(var.configuration.subnet_ids) <= 3 &&
      alltrue([for id in var.configuration.subnet_ids : can(regex("^subnet-[a-f0-9]+$", id))]) &&
      length(var.configuration.security_group_ids) == 1 &&
      alltrue([for id in var.configuration.security_group_ids : can(regex("^sg-[a-f0-9]+$", id))])
    )
    error_message = "D0 requires an exact dev account/image digest and reviewed existing RDS/network metadata."
  }
}

variable "runtime_enabled" {
  description = "Create the runtime OIDC role only after installation has been verified."
  type        = bool
  default     = false
}
