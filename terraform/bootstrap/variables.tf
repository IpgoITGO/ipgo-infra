variable "aws_region" {
  description = "Region that stores Terraform state."
  type        = string
  default     = "ap-northeast-2"
}

variable "bucket_prefix" {
  description = "Globally unique S3 state bucket prefix."
  type        = string
  default     = "ipgo-terraform-state-"
}

variable "github_owner" {
  description = "GitHub organization allowed to assume deployment roles."
  type        = string
  default     = "IpgoITGO"
}

variable "github_owner_id" {
  description = "Immutable GitHub organization ID used in OIDC subject claims."
  type        = string
  default     = "346794439"
}

variable "github_infra_repository_id" {
  description = "Immutable GitHub repository ID for ipgo-infra."
  type        = string
  default     = "1437964038"
}

variable "github_server_repository_id" {
  description = "Immutable GitHub repository ID for ipgo-server."
  type        = string
  default     = "1430767744"
}

variable "github_ai_repository_id" {
  description = "Immutable GitHub repository ID for ipgo-ai."
  type        = string
  default     = "1430768259"
}

variable "github_oidc_provider_arn" {
  description = "Existing GitHub Actions OIDC provider ARN. Leave null to create it in this bootstrap stack."
  type        = string
  default     = null
  nullable    = true
}
