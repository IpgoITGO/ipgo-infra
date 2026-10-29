output "cluster_arn" {
  value = aws_ecs_cluster.this.arn
}

output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "server_repository_url" {
  value = aws_ecr_repository.server.repository_url
}

output "ai_repository_url" {
  value = aws_ecr_repository.ai.repository_url
}

output "server_log_group_name" {
  value = aws_cloudwatch_log_group.server.name
}

output "ai_log_group_name" {
  value = aws_cloudwatch_log_group.ai.name
}

output "service_connect_namespace_arn" {
  value = aws_service_discovery_private_dns_namespace.this.arn
}

output "alb_arn" {
  value = aws_lb.this.arn
}

output "alb_dns_name" {
  value = aws_lb.this.dns_name
}

output "server_target_group_arn" {
  value = aws_lb_target_group.server.arn
}
