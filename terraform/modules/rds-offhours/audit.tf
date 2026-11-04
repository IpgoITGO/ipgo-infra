resource "aws_ecs_task_definition" "audit" {
  family                   = "${local.name}-audit"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.audit_execution.arn
  task_role_arn            = aws_iam_role.audit_task.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  container_definitions = jsonencode([{
    name                   = "audit", image = var.config.audit_image, essential = true,
    readonlyRootFilesystem = true, user = "65534:65534", stopTimeout = 10,
    environment = [{ name = "PYTHONDONTWRITEBYTECODE", value = "1" },
      { name = "AUDIT_CONFIG", value = jsonencode({
        db_arn     = var.config.db_arn, host = var.config.audit_host,
        database   = var.config.audit_database, reference_run_id = var.config.audit_reference_run_id,
        secret_arn = var.config.audit_secret_arn, bucket = var.config.bucket, result_prefix = var.config.result_prefix
    }) }],
    logConfiguration = { logDriver = "awslogs", options = {
      awslogs-group = var.config.audit_log_group_name, awslogs-region = var.config.region, awslogs-stream-prefix = "rds-offhours"
    } }
  }])
  depends_on = [aws_iam_role_policy.audit_task, aws_iam_role_policy.audit_execution]
}

resource "aws_cloudwatch_metric_alarm" "workflow_failure" {
  for_each            = toset(["ExecutionsFailed", "ExecutionsTimedOut"])
  alarm_name          = "${local.name}-${each.value}"
  namespace           = "AWS/States"
  metric_name         = each.value
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { StateMachineArn = aws_sfn_state_machine.controller.arn }
  alarm_actions       = [var.config.alarm_topic_arn]
}
resource "aws_cloudwatch_metric_alarm" "dispatcher_failure" {
  alarm_name          = "${local.name}-dispatcher-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { FunctionName = aws_lambda_function.dispatcher.function_name }
  alarm_actions       = [var.config.alarm_topic_arn]
}
