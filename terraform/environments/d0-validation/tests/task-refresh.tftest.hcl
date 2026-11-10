mock_provider "aws" {
  mock_resource "aws_ecs_task_definition" {
    override_during = apply
    defaults        = { arn = "arn:aws:ecs:ap-northeast-2:123456789012:task-definition/ipgo-dev-d0-validation:7" }
  }
  mock_resource "aws_iam_role" {
    override_during = apply
    defaults        = { arn = "arn:aws:iam::123456789012:role/ipgo-dev-d0-execution" }
  }
  mock_resource "aws_secretsmanager_secret" {
    override_during = apply
    defaults        = { arn = "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:/ipgo/dev/d0-bootstrap-Abc123" }
  }
  mock_resource "aws_cloudwatch_log_group" {
    override_during = apply
    defaults        = { arn = "arn:aws:logs:ap-northeast-2:123456789012:log-group:/ipgo/dev/d0-validation" }
  }
}
variables {
  enabled         = true
  runtime_enabled = false
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
run "mock_installation" {
  command = apply
}
run "mock_image_refresh" {
  command = plan
  variables {
    configuration = merge({

      account_id                   = "123456789012"
      image_uri                    = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/ipgo-dev/database@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      bootstrap_execution_role_arn = "arn:aws:iam::123456789012:role/ipgo-dev-database-bootstrap-execution"
      master_secret_arn            = "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:rds!db-example-Abc123"
      installation_log_group       = "/ipgo/ipgo-dev/database"
      db_host                      = "ipgo-dev.abcdefgh.ap-northeast-2.rds.amazonaws.com"
      db_name                      = "ipgo"
      subnet_ids                   = ["subnet-0abcd"]
      security_group_ids           = ["sg-0abcd"]
    }, { image_uri = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/ipgo-dev/database@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" })
  }
  assert {
    condition     = module.d0[0].installation.task_definition_arn != null
    error_message = "The installation task must remain defined."
  }
}
