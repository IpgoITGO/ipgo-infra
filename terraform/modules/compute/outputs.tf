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

output "database_repository_url" {
  value = aws_ecr_repository.database.repository_url
}

output "server_log_group_name" {
  value = aws_cloudwatch_log_group.server.name
}

output "ai_log_group_name" {
  value = aws_cloudwatch_log_group.ai.name
}

output "database_log_group_name" {
  value = aws_cloudwatch_log_group.database.name
}

output "service_connect_namespace_arn" {
  value = aws_service_discovery_private_dns_namespace.this.arn
}

output "alb_arn" {
  value = try(aws_lb.this[0].arn, null)
}

output "alb_arn_suffix" {
  value = try(aws_lb.this[0].arn_suffix, null)
}

output "server_target_group_arn_suffix" {
  value = try(aws_lb_target_group.server[0].arn_suffix, null)
}

output "alb_dns_name" {
  value = try(aws_lb.this[0].dns_name, null)
}

output "server_target_group_arn" {
  value = try(aws_lb_target_group.server[0].arn, null)
}

output "server_service_name" {
  value = aws_ecs_service.server.name
}

output "ai_api_service_name" {
  value = aws_ecs_service.ai_api.name
}

output "ai_worker_service_name" {
  value = aws_ecs_service.ai_worker.name
}

output "server_task_definition_family" {
  value = aws_ecs_task_definition.server.family
}

output "ai_api_task_definition_family" {
  value = aws_ecs_task_definition.ai_api.family
}

output "ai_worker_task_definition_family" {
  value = aws_ecs_task_definition.ai_worker.family
}

output "database_bootstrap_task_definition_family" {
  value = aws_ecs_task_definition.database_bootstrap.family
}

output "database_migrate_task_definition_family" {
  value = aws_ecs_task_definition.database_migrate.family
}

output "database_verify_task_definition_family" {
  value = aws_ecs_task_definition.database_verify.family
}
