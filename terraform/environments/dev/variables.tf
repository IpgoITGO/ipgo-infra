variable "aws_region" {
  description = "AWS deployment Region."
  type        = string
  default     = "ap-northeast-2"
}

variable "enable_dev_monitoring" {
  description = "Create the approved development alarms and account budget."
  type        = bool
  default     = false
}

variable "alert_email" {
  description = "Private alert destination, supplied through GitHub Actions secret AWS_ALERT_EMAIL."
  type        = string
  default     = null
  sensitive   = true
  validation {
    condition     = !var.enable_dev_monitoring || can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alert_email))
    error_message = "A valid alert_email is required when development monitoring is enabled."
  }
}

variable "monthly_budget_usd" {
  description = "Account-wide monthly USD cost alert threshold; alerts never stop services."
  type        = number
  default     = 50
  validation {
    condition     = var.monthly_budget_usd > 0
    error_message = "monthly_budget_usd must be positive."
  }
}

variable "container_insights" {
  description = "Detailed ECS telemetry mode, independent of application logs and service metrics."
  type        = string
  default     = "disabled"
  validation {
    condition     = contains(["disabled", "enabled", "enhanced"], var.container_insights)
    error_message = "container_insights must be disabled, enabled, or enhanced."
  }
}

variable "availability_zones" {
  description = "Two Availability Zones used by dev."
  type        = list(string)
  default     = ["ap-northeast-2a", "ap-northeast-2c"]
}

variable "enable_nat_gateway" {
  description = "Create a billable NAT Gateway and keep ECS tasks in private application subnets. Disabled by default for the budget-limited dev environment."
  type        = bool
  default     = false
}

variable "certificate_arn" {
  description = "ACM certificate ARN for the public ALB. Keep null until domain and certificate are approved."
  type        = string
  default     = null
  nullable    = true
}

variable "enable_http_dev_endpoint" {
  description = "Temporarily expose the development backend over HTTP while certificate validation is pending."
  type        = bool
  default     = false
}

variable "https_redirect_host" {
  description = "Canonical API DNS hostname without a scheme, port or path."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.https_redirect_host == null ? true : can(regex("^([a-z0-9]([a-z0-9-]*[a-z0-9])?\\.)+[a-z]{2,63}$", var.https_redirect_host))
    error_message = "https_redirect_host must be a DNS hostname without a scheme, port or path."
  }
}

variable "db_engine_version" {
  description = "PostgreSQL version verified as orderable in the target Region."
  type        = string
  default     = "16.15"
}

variable "db_instance_class" {
  description = "Development RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "server_desired_count" {
  description = "Initial Spring Boot task count. Keep zero until image and secrets are ready."
  type        = number
  default     = 0
}

variable "ai_api_desired_count" {
  description = "Initial FastAPI API task count. Keep zero until image and secrets are ready."
  type        = number
  default     = 0
}

variable "ai_worker_desired_count" {
  description = "Initial FastAPI worker task count. Keep zero until image and secrets are ready."
  type        = number
  default     = 0
}
