variable "name_prefix" {
  description = "Resource name prefix."
  type        = string
}

variable "upload_bucket_arn" {
  description = "Upload bucket ARN."
  type        = string
}

variable "jobs_queue_arn" {
  description = "Engine jobs queue ARN."
  type        = string
}

variable "results_queue_arn" {
  description = "Engine results queue ARN."
  type        = string
}

variable "server_secret_arns" {
  description = "Secrets the Spring task execution role may inject."
  type        = list(string)
  default     = []
}

variable "ai_secret_arns" {
  description = "Secrets the FastAPI task execution role may inject."
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Tags applied to resources."
  type        = map(string)
  default     = {}
}
