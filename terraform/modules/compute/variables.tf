variable "name_prefix" {
  description = "Resource name prefix."
  type        = string
}

variable "vpc_id" {
  description = "VPC ID."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnet IDs for the ALB."
  type        = list(string)
}

variable "alb_security_group_id" {
  description = "ALB security group ID."
  type        = string
}

variable "certificate_arn" {
  description = "ACM certificate ARN. No public listener is created when null."
  type        = string
  default     = null
  nullable    = true
}

variable "server_health_check_path" {
  description = "Spring Boot health check path."
  type        = string
  default     = "/actuator/health"
}

variable "log_retention_days" {
  description = "CloudWatch log retention."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Tags applied to resources."
  type        = map(string)
  default     = {}
}
