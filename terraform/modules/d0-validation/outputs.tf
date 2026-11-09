output "installation" {
  value = {
    task_definition_arn = aws_ecs_task_definition.install.arn
    secret_arn          = aws_secretsmanager_secret.d0.arn
    task_role_arn       = aws_iam_role.installer.arn
    execution_role_arn  = var.configuration.bootstrap_execution_role_arn
    cluster_arn         = local.cluster
    image_uri           = var.configuration.image_uri
    subnet_ids          = var.configuration.subnet_ids
    security_group_ids  = var.configuration.security_group_ids
    log_group           = var.configuration.installation_log_group
  }
}

output "runtime" {
  value = {
    enabled             = var.runtime_enabled
    runner_role_arn     = try(aws_iam_role.runner[0].arn, null)
    task_definition_arn = aws_ecs_task_definition.runtime.arn
    execution_role_arn  = aws_iam_role.execution.arn
    cluster_arn         = local.cluster
    image_uri           = var.configuration.image_uri
    subnet_ids          = var.configuration.subnet_ids
    security_group_ids  = var.configuration.security_group_ids
    log_group           = aws_cloudwatch_log_group.d0.name
  }
}
