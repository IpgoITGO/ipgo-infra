output "state_bucket_name" {
  description = "S3 bucket used by environment backends."
  value       = aws_s3_bucket.terraform_state.id
}

output "github_plan_role_arn" {
  description = "OIDC role used by ipgo-infra plan jobs."
  value       = aws_iam_role.github_plan.arn
}

output "github_apply_role_arn" {
  description = "OIDC role used by approved ipgo-infra apply jobs."
  value       = aws_iam_role.github_apply.arn
}

output "github_server_deploy_role_arn" {
  description = "OIDC role used by ipgo-server dev deployments."
  value       = aws_iam_role.github_server_deploy.arn
}

output "github_ai_deploy_role_arn" {
  description = "OIDC role used by ipgo-ai dev deployments."
  value       = aws_iam_role.github_ai_deploy.arn
}
