mock_provider "aws" {
  mock_resource "aws_ecs_task_definition" {
    override_during = plan
    defaults        = { arn = "arn:aws:ecs:ap-northeast-2:123456789012:task-definition/ipgo-dev-d0-validation:7" }
  }
  mock_resource "aws_iam_role" {
    override_during = plan
    defaults        = { arn = "arn:aws:iam::123456789012:role/ipgo-dev-d0-execution" }
  }
  mock_resource "aws_secretsmanager_secret" {
    override_during = plan
    defaults        = { arn = "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:/ipgo/dev/d0-bootstrap-Abc123" }
  }
  mock_resource "aws_cloudwatch_log_group" {
    override_during = plan
    defaults        = { arn = "arn:aws:logs:ap-northeast-2:123456789012:log-group:/ipgo/dev/d0-validation" }
  }
}
variables {
  configuration = {
    account_id                   = "123456789012"
    image_uri                    = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/ipgo-dev/database@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    bootstrap_execution_role_arn = "arn:aws:iam::123456789012:role/ipgo-dev-database-bootstrap-execution"
    master_secret_arn            = "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:rds!db-example-Abc123"
    installation_log_group       = "/ipgo/ipgo-dev/database"
    db_host                      = "ipgo-dev.abcdefgh.ap-northeast-2.rds.amazonaws.com"
    db_name                      = "ipgo"
    subnet_ids                   = ["subnet-0abcd"]
    security_group_ids           = ["sg-0abcd"]
  }
}
run "installation_has_no_runtime_oidc" {
  command = plan
  assert {
    condition     = aws_ecs_task_definition.install.skip_destroy && aws_ecs_task_definition.runtime.skip_destroy
    error_message = "Both D0 task definitions must retain prior revisions."
  }
  assert {
    condition     = length(aws_iam_role.runner) == 0 && length(aws_iam_role_policy.runner) == 0
    error_message = "Installation must not enable runtime OIDC."
  }
  assert {
    condition     = jsondecode(aws_ecs_task_definition.runtime.container_definitions)[0].secrets[0].valueFrom == format("%s:username::", aws_secretsmanager_secret.d0.arn)
    error_message = "Runtime must receive only the new restricted DB secret."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.installer.policy).Statement[0].Action == ["secretsmanager:PutSecretValue"]
    error_message = "Installer task may write only the D0 secret."
  }
}
run "runtime_trust_and_permissions_are_narrow" {
  command = plan
  variables { runtime_enabled = true }
  assert {
    condition = (
      jsondecode(aws_iam_role.runner[0].assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com" &&
      jsondecode(aws_iam_role.runner[0].assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:IpgoITGO@346794439/ipgo-server@1430767744:environment:d0-validation"
    )
    error_message = "Audience and immutable repository/environment subject must match exactly."
  }
  assert {
    condition = (
      jsondecode(aws_iam_role_policy.runner[0].policy).Statement[0].Resource == aws_ecs_task_definition.runtime.arn &&
      jsondecode(aws_iam_role_policy.runner[0].policy).Statement[0].Condition.Bool["ecs:enable-execute-command"] == "false" &&
      jsondecode(aws_iam_role_policy.runner[0].policy).Statement[0].Condition.StringEquals["ecs:task-memory"] == "512"
    )
    error_message = "RunTask must bind one exact revision and resource/execution constraints."
  }
  assert {
    condition = alltrue([for s in jsondecode(aws_iam_role_policy.runner[0].policy).Statement :
      s.Resource != "*" && !contains(["ecs:UpdateService", "ecs:RegisterTaskDefinition", "ssm:SendCommand", "secretsmanager:GetSecretValue", "iam:CreateRole"], s.Action)
    ])
    error_message = "Runtime role must not gain wildcard/general administrator permissions."
  }
  assert {
    condition = (
      jsondecode(aws_iam_role_policy.runner[0].policy).Statement[5].Resource == aws_iam_role.execution.arn &&
      jsondecode(aws_iam_role_policy.runner[0].policy).Statement[3].Condition.StringEquals["aws:ResourceTag/Purpose"] == "d0-synthetic"
    )
    error_message = "PassRole/StopTask must not reach installation or application roles/tasks."
  }
  assert {
    condition = (
      aws_ecs_task_definition.runtime.task_role_arn == null &&
      jsondecode(aws_ecs_task_definition.runtime.container_definitions)[0].readonlyRootFilesystem &&
      !jsondecode(aws_ecs_task_definition.runtime.container_definitions)[0].privileged
    )
    error_message = "Runtime task must not receive AWS task credentials or a privileged writable root."
  }
}
