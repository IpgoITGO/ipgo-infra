mock_provider "aws" {
  mock_resource "aws_iam_role" { defaults = { arn = "arn:aws:iam::111111111111:role/test" } }
  mock_resource "aws_lambda_function" { defaults = { arn = "arn:aws:lambda:ap-northeast-2:111111111111:function:test" } }
  mock_resource "aws_sfn_state_machine" { defaults = { arn = "arn:aws:states:ap-northeast-2:111111111111:stateMachine:test" } }
  mock_resource "aws_ecs_task_definition" { defaults = { arn = "arn:aws:ecs:ap-northeast-2:111111111111:task-definition/test:1" } }
  mock_resource "aws_scheduler_schedule_group" { defaults = { arn = "arn:aws:scheduler:ap-northeast-2:111111111111:schedule-group/test" } }
  mock_resource "aws_cloudwatch_log_group" { defaults = { arn = "arn:aws:logs:ap-northeast-2:111111111111:log-group:/test" } }
  mock_resource "aws_dynamodb_table" { defaults = { arn = "arn:aws:dynamodb:ap-northeast-2:111111111111:table/test" } }
  mock_resource "aws_cloudwatch_event_rule" { defaults = { arn = "arn:aws:events:ap-northeast-2:111111111111:rule/test" } }

  mock_data "aws_caller_identity" { defaults = { account_id = "111111111111" } }
  mock_data "aws_partition" { defaults = { partition = "aws" } }
}
# archive는 로컬 zip 생성만 수행하며 AWS는 전부 mock이다.
provider "archive" {}
variables { config = { "name" : "test-rds-202611", "region" : "ap-northeast-2", "db_id" : "test-db", "db_arn" : "arn:aws:rds:ap-northeast-2:111111111111:db:test-db", "revision" : "v1", "stop_not_before" : "2026-11-10T04:00:00+09:00", "stop_disabled_from" : "2026-11-30T00:00:00+09:00", "bucket" : "test-evidence", "manifest_key" : "rds/approval.json", "manifest_version" : "fixed-version", "manifest_sha256" : "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "result_prefix" : "rds/results", "writer_instance_ids" : ["i-11111111111111111"], "cluster_arn" : "arn:aws:ecs:ap-northeast-2:111111111111:cluster/test", "queue_urls" : ["https://sqs.ap-northeast-2.amazonaws.com/111111111111/a", "https://sqs.ap-northeast-2.amazonaws.com/111111111111/b", "https://sqs.ap-northeast-2.amazonaws.com/111111111111/c", "https://sqs.ap-northeast-2.amazonaws.com/111111111111/d"], "queue_arns" : ["arn:aws:sqs:ap-northeast-2:111111111111:a", "arn:aws:sqs:ap-northeast-2:111111111111:b", "arn:aws:sqs:ap-northeast-2:111111111111:c", "arn:aws:sqs:ap-northeast-2:111111111111:d"], "existing_schedule_arns" : ["arn:aws:scheduler:ap-northeast-2:111111111111:schedule/old/start", "arn:aws:scheduler:ap-northeast-2:111111111111:schedule/old/stop"], "service_arns" : ["arn:aws:ecs:ap-northeast-2:111111111111:service/test/server", "arn:aws:ecs:ap-northeast-2:111111111111:service/test/ai"], "service_task_arns" : ["arn:aws:ecs:ap-northeast-2:111111111111:task-definition/server:1", "arn:aws:ecs:ap-northeast-2:111111111111:task-definition/ai:1"], "audit_image" : "111111111111.dkr.ecr.ap-northeast-2.amazonaws.com/test@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "audit_repository_arn" : "arn:aws:ecr:ap-northeast-2:111111111111:repository/test", "audit_subnets" : ["subnet-11111111"], "audit_security_groups" : ["sg-11111111"], "audit_secret_arn" : "arn:aws:secretsmanager:ap-northeast-2:111111111111:secret:test-AbCdEf", "audit_secret_kms_arn" : "", "audit_host" : "test.invalid", "audit_database" : "ipgo", "audit_reference_run_id" : 1, "audit_log_group_name" : "/test/db-audit", "alarm_topic_arn" : "arn:aws:sns:ap-northeast-2:111111111111:test" } }
run "disabled_default_and_least_privilege" {
  # mock provider 내부 상태 평가만 수행한다. 실제 AWS apply는 하지 않는다.
  command = apply
  assert {
    condition     = alltrue([for s in aws_scheduler_schedule.rds : s.state == "DISABLED"])
    error_message = "승인 전 모든 새 예약은 비활성이어야 합니다."
  }
  assert {
    condition     = !jsondecode(aws_lambda_function.controller.environment[0].variables.CONFIG).apply_approved && !jsondecode(aws_lambda_function.controller.environment[0].variables.CONFIG).stop_enabled
    error_message = "런타임 이중 스위치를 유지해야 합니다."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.controller.policy).Statement[1].Resource == var.config.db_arn
    error_message = "Start/Stop은 같은 DB ARN 한 개에만 허용해야 합니다."
  }
  assert {
    condition     = alltrue([for s in jsondecode(aws_iam_role_policy.controller.policy).Statement : !contains(try(tolist(s.Action), [tostring(s.Action)]), "scheduler:UpdateSchedule")])
    error_message = "실행기가 기존 예약을 변경할 수 없어야 합니다."
  }
  assert {
    condition     = jsondecode(aws_ecs_task_definition.audit.container_definitions)[0].readonlyRootFilesystem && aws_ecs_task_definition.audit.network_mode == "awsvpc"
    error_message = "감사는 고립된 읽기전용 task이어야 합니다."
  }
  assert {
    condition     = length(keys(jsondecode(aws_sfn_state_machine.controller.definition).States.Tick)) == 7 && !can(jsondecode(aws_sfn_state_machine.controller.definition).States.Tick.Retry)
    error_message = "쓰기 포함 tick은 자동 재시도하지 않습니다."
  }
}
run "stop_cannot_enable_without_approval" {
  command = plan
  variables { stop_enabled = true }
  expect_failures = [aws_scheduler_schedule.rds]
}
