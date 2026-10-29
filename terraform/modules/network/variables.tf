variable "name_prefix" {
  description = "Resource name prefix."
  type        = string
}

variable "vpc_cidr" {
  description = "VPC IPv4 CIDR."
  type        = string
}

variable "availability_zones" {
  description = "Availability Zones used by the environment."
  type        = list(string)

  validation {
    condition     = length(var.availability_zones) >= 2
    error_message = "At least two Availability Zones are required."
  }
}

variable "public_subnet_cidrs" {
  description = "Public subnet CIDRs, one per Availability Zone."
  type        = list(string)
}

variable "app_subnet_cidrs" {
  description = "Private application subnet CIDRs, one per Availability Zone."
  type        = list(string)
}

variable "database_subnet_cidrs" {
  description = "Isolated database subnet CIDRs, one per Availability Zone."
  type        = list(string)
}

variable "enable_nat_gateway" {
  description = "Create one shared NAT Gateway for private application subnets."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags applied to resources."
  type        = map(string)
  default     = {}
}
