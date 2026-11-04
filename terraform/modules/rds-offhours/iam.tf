locals {
  log_statement = { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.runtime.arn}:*" }
}

resource "aws_iam_role_policy" "dispatcher" {
  role = aws_iam_role.dispatcher.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    local.log_statement,
    { Effect = "Allow", Action = "states:StartExecution", Resource = local.runtime_config.state_machine_arn }
  ] })
}
resource "aws_iam_role_policy" "controller" {
  role = aws_iam_role.controller.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    local.log_statement,
    { Effect = "Allow", Action = ["rds:StartDBInstance", "rds:StopDBInstance"], Resource = var.config.db_arn },
    { Effect = "Allow", Action = "sns:Publish", Resource = var.config.alarm_topic_arn },
    # 목록형 API는 자원 수준 제한을 지원하지 않는다. 대상은 고정 코드로 전달한다.
    { Effect = "Allow", Action = ["rds:DescribeDBInstances", "rds:DescribeDBSnapshots", "rds:DescribePendingMaintenanceActions", "ec2:DescribeInstances", "cloudwatch:GetMetricStatistics"], Resource = "*", Condition = { StringEquals = { "aws:RequestedRegion" = var.config.region } } },
    { Effect = "Allow", Action = ["ecs:ListTasks", "ecs:DescribeTasks", "ecs:DescribeContainerInstances"], Resource = "*", Condition = { ArnEquals = { "ecs:cluster" = var.config.cluster_arn } } },
    { Effect = "Allow", Action = "ecs:DescribeServices", Resource = var.config.service_arns },
    # DescribeTaskDefinition은 AWS가 자원 수준 제한을 지원하지 않는다.
    # 런타임은 service_task_arns에 고정된 revision만 조회하고 digest를 대조한다.
    { Effect = "Allow", Action = "ecs:DescribeTaskDefinition", Resource = "*", Condition = { StringEquals = { "aws:RequestedRegion" = var.config.region } } },
    { Effect = "Allow", Action = "states:ListExecutions", Resource = local.runtime_config.state_machine_arn },
    { Effect = "Allow", Action = "scheduler:GetSchedule", Resource = var.config.existing_schedule_arns },
    { Effect = "Allow", Action = "sqs:GetQueueAttributes", Resource = var.config.queue_arns },
    { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:PutItem", "dynamodb:ConditionCheckItem"], Resource = aws_dynamodb_table.ledger.arn },
    { Effect = "Allow", Action = "s3:GetObjectVersion", Resource = "${local.base}:s3:::${var.config.bucket}/${var.config.manifest_key}", Condition = { StringEquals = { "s3:VersionId" = var.config.manifest_version } } },
    { Effect = "Allow", Action = "s3:GetObject", Resource = "${local.base}:s3:::${var.config.bucket}/${var.config.result_prefix}/*" },
    { Effect = "Allow", Action = "ecs:RunTask", Resource = aws_ecs_task_definition.audit.arn, Condition = { ArnEquals = { "ecs:cluster" = var.config.cluster_arn } } },
    { Effect = "Allow", Action = "ecs:TagResource", Resource = "${local.base}:ecs:${var.config.region}:${local.account}:task/*", Condition = { StringEquals = { "ecs:CreateAction" = "RunTask", "aws:RequestTag/Controller" = local.name } } },
    { Effect = "Allow", Action = "ecs:StopTask", Resource = "${local.base}:ecs:${var.config.region}:${local.account}:task/*", Condition = { ArnEquals = { "ecs:cluster" = var.config.cluster_arn }, StringEquals = { "aws:ResourceTag/Controller" = local.name } } },
    { Effect = "Allow", Action = "iam:PassRole", Resource = [aws_iam_role.audit_task.arn, aws_iam_role.audit_execution.arn], Condition = { StringEquals = { "iam:PassedToService" = "ecs-tasks.amazonaws.com" } } }
  ] })
}

resource "aws_iam_role" "audit_task" {
  name               = "${local.name}-audit-task"
  assume_role_policy = jsonencode(local.assume.tasks)
}
resource "aws_iam_role_policy" "audit_task" {
  role = aws_iam_role.audit_task.id
  policy = jsonencode({ Version = "2012-10-17", Statement = concat([
    { Effect = "Allow", Action = "secretsmanager:GetSecretValue", Resource = var.config.audit_secret_arn },
    { Effect = "Allow", Action = "s3:PutObject", Resource = "${local.base}:s3:::${var.config.bucket}/${var.config.result_prefix}/*", Condition = { StringEquals = { "s3:x-amz-server-side-encryption" = "AES256" } } }
    ], var.config.audit_secret_kms_arn == "" ? [] : [
    { Effect = "Allow", Action = "kms:Decrypt", Resource = var.config.audit_secret_kms_arn, Condition = { StringEquals = { "kms:ViaService" = "secretsmanager.${var.config.region}.amazonaws.com", "kms:EncryptionContext:SecretARN" = var.config.audit_secret_arn } } }
  ]) })
}
resource "aws_iam_role" "audit_execution" {
  name               = "${local.name}-audit-execution"
  assume_role_policy = jsonencode(local.assume.tasks)
}
resource "aws_iam_role_policy" "audit_execution" {
  role = aws_iam_role.audit_execution.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = "ecr:GetAuthorizationToken", Resource = "*" },
    { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"], Resource = var.config.audit_repository_arn },
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${local.base}:logs:${var.config.region}:${local.account}:log-group:${var.config.audit_log_group_name}:*" }
  ] })
}
