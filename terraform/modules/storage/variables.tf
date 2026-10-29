variable "name_prefix" {
  description = "Resource name prefix."
  type        = string
}

variable "noncurrent_version_expiration_days" {
  description = "Days to retain noncurrent upload object versions."
  type        = number
  default     = 90
}

variable "tags" {
  description = "Tags applied to resources."
  type        = map(string)
  default     = {}
}
