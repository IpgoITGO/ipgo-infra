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

variable "max_message_size" {
  description = "Maximum SQS body size in bytes, including dead-letter queues."
  type        = number
  default     = 262144
  validation {
    condition     = var.max_message_size >= 1024 && var.max_message_size <= 1048576 && floor(var.max_message_size) == var.max_message_size
    error_message = "SQS message size must be an integer between 1024 and 1048576 bytes."
  }
}
