# 기존 dev state와 분리한다. 기본 자원 0개이며 기존 예약은 관리하지 않는다.
terraform {
  required_version = ">= 1.10.0, < 2.0.0"
  required_providers {
    aws     = { source = "hashicorp/aws", version = ">= 6.0, < 7.0" }
    archive = { source = "hashicorp/archive", version = ">= 2.7, < 3.0" }
  }
  backend "s3" {}
}
provider "aws" { region = var.aws_region }
variable "aws_region" {
  type    = string
  default = "ap-northeast-2"
}
variable "create_resources" {
  type    = bool
  default = false
}
variable "apply_approved" {
  type    = bool
  default = false
}
variable "schedules_enabled" {
  type    = bool
  default = false
}
variable "stop_enabled" {
  type    = bool
  default = false
}
variable "config" {
  description = "로컬 비공개 tfvars의 식별자/해시만. Secret 값 금지. module이 실제 구조를 검증한다."
  type        = any
  default     = null
}
module "rds_offhours" {
  count             = var.create_resources ? 1 : 0
  source            = "../../modules/rds-offhours"
  config            = var.config
  apply_approved    = var.apply_approved
  schedules_enabled = var.schedules_enabled
  stop_enabled      = var.stop_enabled
}
output "review" {
  value = { status = var.create_resources ? "REVIEW_REQUIRED" : "NO_RESOURCES_DISABLED", resources = module.rds_offhours[*].review }
}
