variable "config" {
  description = "검토 후 고정할 대상·기존 자원. Secret 값이 아니라 ARN/ID만 전달한다."
  type = object({
    name                   = string
    region                 = string
    db_id                  = string
    db_arn                 = string
    revision               = string
    stop_not_before        = string
    stop_disabled_from     = string
    bucket                 = string
    manifest_key           = string
    manifest_version       = string
    manifest_sha256        = string
    result_prefix          = string
    writer_instance_ids    = list(string)
    cluster_arn            = string
    queue_urls             = list(string)
    queue_arns             = list(string)
    existing_schedule_arns = list(string)
    service_arns           = list(string)
    service_task_arns      = list(string)
    audit_image            = string
    audit_repository_arn   = string
    audit_subnets          = list(string)
    audit_security_groups  = list(string)
    audit_secret_arn       = string
    audit_secret_kms_arn   = string
    audit_host             = string
    audit_database         = string
    audit_reference_run_id = number
    audit_log_group_name   = string
    alarm_topic_arn        = string
  })
  validation {
    condition = (length(distinct(var.config.queue_arns)) == 4 && length(distinct(var.config.queue_urls)) == 4 &&
      length(var.config.writer_instance_ids) > 0 && length(var.config.audit_subnets) > 0 &&
      length(var.config.audit_security_groups) > 0 && length(var.config.service_arns) >= 2 &&
      length(var.config.service_task_arns) >= 2 && length(var.config.existing_schedule_arns) == 2 &&
      can(regex("@sha256:[0-9a-f]{64}$", var.config.audit_image)) &&
      can(regex("^[0-9a-f]{64}$", var.config.manifest_sha256)) &&
    length(var.config.manifest_version) > 0 && var.config.audit_reference_run_id > 0)
    error_message = "고정 digest·버전, 기존 예약2개·큐4개·writer·서비스·기존 감사 네트워크를 명시해야 합니다."
  }
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

terraform {
  required_providers {
    aws     = { source = "hashicorp/aws", version = ">= 6.0, < 7.0" }
    archive = { source = "hashicorp/archive", version = ">= 2.7, < 3.0" }
  }
}
