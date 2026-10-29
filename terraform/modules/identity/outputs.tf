output "server_execution_role_arn" {
  value = aws_iam_role.execution["server"].arn
}

output "ai_execution_role_arn" {
  value = aws_iam_role.execution["ai"].arn
}

output "database_bootstrap_execution_role_arn" {
  value = aws_iam_role.execution["database-bootstrap"].arn
}

output "database_migrate_execution_role_arn" {
  value = aws_iam_role.execution["database-migrate"].arn
}

output "database_verify_execution_role_arn" {
  value = aws_iam_role.execution["database-verify"].arn
}

output "server_task_role_arn" {
  value = aws_iam_role.server_task.arn
}

output "ai_task_role_arn" {
  value = aws_iam_role.ai_task.arn
}
