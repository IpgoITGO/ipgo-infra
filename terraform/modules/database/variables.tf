variable "name_prefix" {
  description = "Resource name prefix."
  type        = string
}

variable "subnet_ids" {
  description = "Isolated database subnet IDs."
  type        = list(string)
}

variable "security_group_ids" {
  description = "Security groups attached to RDS."
  type        = list(string)
}

variable "database_name" {
  description = "Initial PostgreSQL database name."
  type        = string
  default     = "ipgo"
}

variable "master_username" {
  description = "RDS bootstrap administrator name. Password is managed by RDS in Secrets Manager."
  type        = string
  default     = "ipgo_admin"
}

variable "engine_version" {
  description = "PostgreSQL engine version. Pin after checking availability in the target Region."
  type        = string
  default     = null
  nullable    = true
}

variable "instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "allocated_storage" {
  description = "Initial storage in GiB."
  type        = number
  default     = 20
}

variable "max_allocated_storage" {
  description = "Storage autoscaling ceiling in GiB."
  type        = number
  default     = 100
}

variable "multi_az" {
  description = "Enable Multi-AZ deployment."
  type        = bool
  default     = false
}

variable "deletion_protection" {
  description = "Protect the DB from deletion."
  type        = bool
  default     = false
}

variable "skip_final_snapshot" {
  description = "Skip a final snapshot when deleting the DB. Dev defaults to true."
  type        = bool
  default     = true
}

variable "backup_retention_period" {
  description = "Automated backup retention in days."
  type        = number
  default     = 7
}

variable "tags" {
  description = "Tags applied to resources."
  type        = map(string)
  default     = {}
}
