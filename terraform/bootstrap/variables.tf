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

variable "github_oidc_provider_arn" {
  description = "Existing GitHub Actions OIDC provider ARN. Leave null to create it in this bootstrap stack."
  type        = string
  default     = null
  nullable    = true
}
