output "vpc_id" {
  description = "VPC ID."
  value       = aws_vpc.this.id
}

output "public_subnet_ids" {
  description = "Public subnet IDs."
  value       = aws_subnet.public[*].id
}

output "app_subnet_ids" {
  description = "Private application subnet IDs."
  value       = aws_subnet.app[*].id
}

output "database_subnet_ids" {
  description = "Isolated database subnet IDs."
  value       = aws_subnet.database[*].id
}
