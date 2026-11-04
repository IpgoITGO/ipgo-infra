data "aws_partition" "current" {}
data "aws_caller_identity" "current" {}
locals {
  partition = data.aws_partition.current.partition
  account   = data.aws_caller_identity.current.account_id
  base      = "arn:${local.partition}"
  name      = var.config.name
  slots = {
    backup00      = "cron(0 0 * 11 ? 2026)"
    stop04        = "cron(0 4 * 11 ? 2026)"
    business07    = "cron(0 7 ? 11 MON-FRI 2026)"
    maintenance22 = "cron(0 22 ? 11 SAT 2026)"
  }
  runtime_config = merge({ for k, v in var.config : k => v if contains([
    "name", "region", "db_id", "db_arn", "revision", "stop_not_before", "stop_disabled_from",
    "bucket", "manifest_key", "manifest_version", "manifest_sha256", "result_prefix",
    "writer_instance_ids", "cluster_arn", "queue_urls", "service_arns", "service_task_arns", "existing_schedule_arns", "audit_image",
    "audit_subnets", "audit_security_groups", "alarm_topic_arn"
    ], k) }, {
    apply_approved    = var.apply_approved
    stop_enabled      = var.stop_enabled
    ledger_table      = aws_dynamodb_table.ledger.name
    state_machine_arn = "${local.base}:states:${var.config.region}:${local.account}:stateMachine:${local.name}"
    audit_task_arn    = aws_ecs_task_definition.audit.arn
  })
  assume = {
    lambda = { Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "lambda.amazonaws.com" } }] }
    tasks  = { Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "ecs-tasks.amazonaws.com" }, Condition = { StringEquals = { "aws:SourceAccount" = local.account }, ArnLike = { "aws:SourceArn" = "${local.base}:ecs:${var.config.region}:${local.account}:*" } } }] }
  }
}

data "archive_file" "runtime" {
  type             = "zip"
  source_dir       = "${path.module}/../../../runtime/rds_offhours"
  output_path      = "${path.root}/.terraform/rds-offhours.zip"
  output_file_mode = "0644"
  excludes         = ["__pycache__", "Dockerfile", "requirements.txt", "audit-role.sql"]
}

resource "aws_dynamodb_table" "ledger" {
  name         = "${local.name}-ledger"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"
  attribute {
    name = "id"
    type = "S"
  }
  server_side_encryption { enabled = true }
  point_in_time_recovery { enabled = true }
  deletion_protection_enabled = true
  lifecycle { prevent_destroy = true }
}

resource "aws_cloudwatch_log_group" "runtime" {
  name              = "/aws/lambda/${local.name}"
  retention_in_days = 14
}

resource "aws_iam_role" "controller" {
  name               = "${local.name}-controller"
  assume_role_policy = jsonencode(local.assume.lambda)
}
resource "aws_iam_role" "dispatcher" {
  name               = "${local.name}-dispatcher"
  assume_role_policy = jsonencode(local.assume.lambda)
}
resource "aws_lambda_function" "controller" {
  function_name                  = "${local.name}-controller"
  role                           = aws_iam_role.controller.arn
  handler                        = "controller.handler"
  runtime                        = "python3.12"
  filename                       = data.archive_file.runtime.output_path
  source_code_hash               = data.archive_file.runtime.output_base64sha256
  timeout                        = 60
  memory_size                    = 256
  reserved_concurrent_executions = 1
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.runtime.name
  }
  environment { variables = { CONFIG = jsonencode(local.runtime_config) } }
  lifecycle {
    precondition {
      condition     = length(base64encode(jsonencode(local.runtime_config))) <= 5200
      error_message = "런타임 CONFIG가 Lambda 환경변수 한도를 넘습니다. 비밀값 없이 고정 설정을 줄여야 합니다."
    }
  }
  depends_on = [aws_iam_role_policy.controller]
}
resource "aws_lambda_function" "dispatcher" {
  function_name    = "${local.name}-dispatcher"
  role             = aws_iam_role.dispatcher.arn
  handler          = "dispatcher.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.runtime.output_path
  source_code_hash = data.archive_file.runtime.output_base64sha256
  timeout          = 20
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.runtime.name
  }
  environment { variables = { CONFIG = jsonencode({
    apply_approved = var.apply_approved, db_arn = var.config.db_arn,
    revision       = var.config.revision, state_machine_arn = local.runtime_config.state_machine_arn
  }) } }
  depends_on = [aws_iam_role_policy.dispatcher]
}
resource "aws_lambda_function_event_invoke_config" "dispatcher" {
  function_name                = aws_lambda_function.dispatcher.function_name
  maximum_event_age_in_seconds = 60
  maximum_retry_attempts       = 0
}

resource "aws_iam_role" "workflow" {
  name = "${local.name}-workflow"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "states.amazonaws.com" }, Condition = {
    StringEquals = { "aws:SourceAccount" = local.account }
    ArnEquals    = { "aws:SourceArn" = local.runtime_config.state_machine_arn }
  } }] })
}
resource "aws_iam_role_policy" "workflow" {
  role   = aws_iam_role.workflow.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = "lambda:InvokeFunction", Resource = aws_lambda_function.controller.arn }] })
}
resource "aws_sfn_state_machine" "controller" {
  name     = local.name
  role_arn = aws_iam_role.workflow.arn
  type     = "STANDARD"
  definition = jsonencode({
    StartAt = "Tick", TimeoutSeconds = 11400, States = {
      Tick = { Type = "Task", Resource = aws_lambda_function.controller.arn, ResultPath = "$.tick", TimeoutSeconds = 65,
        Parameters = { "key.$" = "$.key", "slot.$" = "$.slot", "scheduled_at.$" = "$.scheduled_at" }, Next = "Decision",
      Catch = [{ ErrorEquals = ["States.ALL"], ResultPath = null, Next = "Failure" }] }
      Decision = { Type = "Choice", Choices = [
        { Variable = "$.tick.status", StringEquals = "WAIT", Next = "Wait" },
        { Variable = "$.tick.status", StringEquals = "FAILED", Next = "Failure" }
      ], Default = "Done" }
      Wait    = { Type = "Wait", Seconds = 60, Next = "Tick" }
      Done    = { Type = "Succeed" }
      Failure = { Type = "Fail", Error = "RDSOffhoursBlocked", Cause = "Inspect typed ledger/logs; do not retry stop blindly" }
    }
  })
  depends_on = [aws_iam_role_policy.workflow]
}

resource "aws_scheduler_schedule_group" "rds" { name = local.name }
resource "aws_iam_role" "scheduler" {
  name = "${local.name}-scheduler"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "scheduler.amazonaws.com" }, Condition = {
    StringEquals = { "aws:SourceAccount" = local.account }
    ArnEquals    = { "aws:SourceArn" = aws_scheduler_schedule_group.rds.arn }
  } }] })
}
resource "aws_iam_role_policy" "scheduler" {
  role   = aws_iam_role.scheduler.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = "lambda:InvokeFunction", Resource = aws_lambda_function.dispatcher.arn }] })
}
resource "aws_scheduler_schedule" "rds" {
  for_each                     = local.slots
  name                         = "${local.name}-${each.key}"
  group_name                   = aws_scheduler_schedule_group.rds.name
  schedule_expression          = each.value
  schedule_expression_timezone = "Asia/Seoul"
  state                        = var.apply_approved && var.schedules_enabled && (each.key != "stop04" || var.stop_enabled) ? "ENABLED" : "DISABLED"
  flexible_time_window { mode = "OFF" }
  target {
    arn      = aws_lambda_function.dispatcher.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = "{\"slot\":\"${each.key}\",\"scheduled_at\":\"<aws.scheduler.scheduled-time>\"}"
    retry_policy {
      maximum_event_age_in_seconds = 60
      maximum_retry_attempts       = 0
    }
  }
  lifecycle {
    precondition {
      condition     = !var.stop_enabled || (var.apply_approved && var.schedules_enabled)
      error_message = "stop은 별도 승인과 start 경로 활성화 없이 켤 수 없습니다."
    }
  }
}
