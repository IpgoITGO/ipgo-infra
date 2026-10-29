output "vpc_id" {
  value = module.network.vpc_id
}

output "upload_bucket_name" {
  value = module.storage.bucket_name
}

output "jobs_queue_url" {
  value = module.messaging.jobs_queue_url
}

output "results_queue_url" {
  value = module.messaging.results_queue_url
}

output "database_endpoint" {
  value     = module.database.endpoint
  sensitive = true
}

output "database_master_secret_arn" {
  value     = module.database.master_secret_arn
  sensitive = true
}

output "ecs_cluster_name" {
  value = module.compute.cluster_name
}

output "server_repository_url" {
  value = module.compute.server_repository_url
}

output "ai_repository_url" {
  value = module.compute.ai_repository_url
}

output "database_repository_url" {
  value = module.compute.database_repository_url
}

output "alb_dns_name" {
  value = module.compute.alb_dns_name
}

output "server_task_role_arn" {
  value = module.identity.server_task_role_arn
}

output "ai_task_role_arn" {
  value = module.identity.ai_task_role_arn
}

output "server_service_name" {
  value = module.compute.server_service_name
}

output "ai_api_service_name" {
  value = module.compute.ai_api_service_name
}

output "ai_worker_service_name" {
  value = module.compute.ai_worker_service_name
}

output "server_task_definition_family" {
  value = module.compute.server_task_definition_family
}

output "ai_api_task_definition_family" {
  value = module.compute.ai_api_task_definition_family
}

output "ai_worker_task_definition_family" {
  value = module.compute.ai_worker_task_definition_family
}

output "database_bootstrap_task_definition_family" {
  value = module.compute.database_bootstrap_task_definition_family
}

output "database_migrate_task_definition_family" {
  value = module.compute.database_migrate_task_definition_family
}

output "database_verify_task_definition_family" {
  value = module.compute.database_verify_task_definition_family
}
