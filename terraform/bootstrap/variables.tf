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
