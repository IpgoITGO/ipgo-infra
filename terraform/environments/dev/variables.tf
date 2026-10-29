variable "aws_region" {
  description = "AWS deployment Region."
  type        = string
  default     = "ap-northeast-2"
}

variable "availability_zones" {
  description = "Two Availability Zones used by dev."
  type        = list(string)
  default     = ["ap-northeast-2a", "ap-northeast-2c"]
}

variable "enable_nat_gateway" {
  description = "Create a billable NAT Gateway for private ECS outbound access."
  type        = bool
  default     = true
}

variable "certificate_arn" {
  description = "ACM certificate ARN for the public ALB. Keep null until domain and certificate are approved."
  type        = string
  default     = null
  nullable    = true
}

variable "db_engine_version" {
  description = "PostgreSQL version available in the target Region. Pin before the first apply."
  type        = string
  default     = null
  nullable    = true
}

variable "db_instance_class" {
  description = "Development RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}
