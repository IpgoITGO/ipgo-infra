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

variable "task_subnet_ids" {
  description = "Subnet IDs for ECS tasks. Use public subnets when NAT is disabled and private application subnets when NAT is enabled."
  type        = list(string)
}

variable "task_assign_public_ip" {
  description = "Assign public IP addresses to ECS tasks so they can reach AWS services and external APIs without a NAT Gateway."
  type        = bool
  default     = false
}

variable "alb_security_group_id" {
  description = "ALB security group ID."
  type        = string
}

variable "server_security_group_id" {
  description = "Security group attached to Spring Boot tasks."
  type        = string
}

variable "ai_security_group_id" {
  description = "Security group attached to FastAPI tasks."
  type        = string
}

variable "server_execution_role_arn" {
  description = "Spring Boot ECS execution role ARN."
  type        = string
}

variable "server_task_role_arn" {
  description = "Spring Boot application task role ARN."
  type        = string
}

variable "ai_execution_role_arn" {
  description = "FastAPI ECS execution role ARN."
  type        = string
}

variable "ai_task_role_arn" {
  description = "FastAPI application task role ARN."
  type        = string
}

variable "database_bootstrap_execution_role_arn" {
  description = "Execution role for the one-off database role bootstrap task."
  type        = string
}

variable "database_migrate_execution_role_arn" {
  description = "Execution role for the one-off Flyway task."
  type        = string
}

variable "database_verify_execution_role_arn" {
  description = "Execution role for the one-off database permission verification task."
  type        = string
}

variable "database_host" {
  description = "Private PostgreSQL hostname used by one-off database tasks."
  type        = string
}

variable "database_port" {
  description = "Private PostgreSQL port."
  type        = number
  default     = 5432
}

variable "database_name" {
  description = "PostgreSQL database name."
  type        = string
  default     = "ipgo"
}

variable "database_master_secret_arn" {
  description = "RDS-managed bootstrap administrator secret ARN."
  type        = string
}

variable "database_migrator_secret_arn" {
  description = "Secrets Manager JSON secret for the Flyway login role."
  type        = string
}

variable "server_database_secret_arn" {
  description = "Secrets Manager JSON secret with url, username and password for Spring Boot."
  type        = string
}

variable "server_jwt_secret_arn" {
  description = "Secrets Manager secret containing the Spring JWT signing secret as a plain string."
  type        = string
}

variable "ai_database_secret_arn" {
  description = "Secrets Manager JSON secret with read-only url, username and password fields for FastAPI and verification."
  type        = string
}

variable "ai_openai_secret_arn" {
  description = "Secrets Manager secret containing the OpenAI API key as a plain string."
  type        = string
}

variable "aws_region" {
  description = "AWS Region exposed to application containers."
  type        = string
}

variable "upload_bucket_name" {
  description = "Private upload bucket read by both applications."
  type        = string
}

variable "jobs_queue_url" {
  description = "SQS engine jobs queue URL."
  type        = string
}

variable "results_queue_url" {
  description = "SQS engine results queue URL."
  type        = string
}

variable "server_desired_count" {
  description = "Initial Spring Boot task count. Keep zero until image and secrets are ready."
  type        = number
  default     = 0

  validation {
    condition     = var.server_desired_count >= 0
    error_message = "server_desired_count must be zero or greater."
  }
}

variable "ai_api_desired_count" {
  description = "Initial FastAPI service task count. Keep zero until image and secrets are ready."
  type        = number
  default     = 0

  validation {
    condition     = var.ai_api_desired_count >= 0
    error_message = "ai_api_desired_count must be zero or greater."
  }
}

variable "ai_worker_desired_count" {
  description = "Initial FastAPI SQS worker count. Keep zero until image and secrets are ready."
  type        = number
  default     = 0

  validation {
    condition     = var.ai_worker_desired_count >= 0
    error_message = "ai_worker_desired_count must be zero or greater."
  }
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
