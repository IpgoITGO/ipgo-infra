output "address" {
  description = "RDS hostname."
  value       = aws_db_instance.this.address
}

output "endpoint" {
  description = "RDS host and port."
  value       = aws_db_instance.this.endpoint
}

output "port" {
  value = aws_db_instance.this.port
}

output "master_secret_arn" {
  description = "RDS-managed bootstrap administrator secret ARN."
  value       = aws_db_instance.this.master_user_secret[0].secret_arn
  sensitive   = true
}
