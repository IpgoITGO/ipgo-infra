variable "name_prefix" {
  description = "Resource name prefix."
  type        = string
}

variable "max_receive_count" {
  description = "Attempts before a message is moved to its DLQ."
  type        = number
  default     = 5
}

variable "visibility_timeout_seconds" {
  description = "Visibility timeout for long engine jobs."
  type        = number
  default     = 900
}

variable "tags" {
  description = "Tags applied to resources."
  type        = map(string)
  default     = {}
}
