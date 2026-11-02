variable "name_prefix" { type = string }
variable "aws_region" { type = string }
variable "cluster_name" { type = string }
variable "alb_arn_suffix" { type = string }
variable "target_group_arn_suffix" { type = string }
variable "database_identifier" { type = string }
variable "services" { type = map(string) }
variable "tags" { type = map(string) }
variable "alert_email" {
  type      = string
  sensitive = true
}
variable "monthly_budget_usd" { type = number }
