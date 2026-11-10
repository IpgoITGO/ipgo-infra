locals {
  account    = var.configuration.account_id
  region     = "ap-northeast-2"
  cluster    = format("arn:aws:ecs:%s:%s:cluster/ipgo-dev-cluster", local.region, local.account)
  tasks      = format("arn:aws:ecs:%s:%s:task/ipgo-dev-cluster/*", local.region, local.account)
  repository = format("arn:aws:ecr:%s:%s:repository/ipgo-dev/database", local.region, local.account)
  subject    = "repo:IpgoITGO@346794439/ipgo-server@1430767744:environment:d0-validation"
  tags       = { Project = "ipgo", Environment = "dev", Purpose = "d0-synthetic" }
  ecs_trust = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = local.account } }
    }]
  })
}

resource "aws_secretsmanager_secret" "d0" {
  name                    = "/ipgo/dev/d0-bootstrap"
  description             = "D0 EXECUTE-only DB login. Value is provisioned inside the approved installer."
  recovery_window_in_days = 30
  tags                    = local.tags
  lifecycle { prevent_destroy = true }
}

resource "aws_cloudwatch_log_group" "d0" {
  name              = "/ipgo/dev/d0-validation"
  retention_in_days = 30
  tags              = local.tags
}

resource "aws_iam_role" "execution" {
  name               = "ipgo-dev-d0-execution"
  assume_role_policy = local.ecs_trust
  tags               = local.tags
}

resource "aws_iam_role_policy" "execution" {
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
      { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"], Resource = local.repository },
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = aws_secretsmanager_secret.d0.arn },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = format("%s:log-stream:d0/runner/*", aws_cloudwatch_log_group.d0.arn) }
    ]
  })
}

resource "aws_iam_role" "installer" {
  name               = "ipgo-dev-d0-install-task"
  assume_role_policy = local.ecs_trust
  tags               = local.tags
}

resource "aws_iam_role_policy" "installer" {
  role = aws_iam_role.installer.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["secretsmanager:PutSecretValue"], Resource = aws_secretsmanager_secret.d0.arn }]
  })
}

resource "aws_ecs_task_definition" "runtime" {
  skip_destroy = true
  lifecycle { create_before_destroy = true }
  family                   = "ipgo-dev-d0-validation"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.execution.arn
  # No task role, ports, service, host mounts, ECS Exec, shell or secret values.
  runtime_platform { operating_system_family = "LINUX" }
  volume { name = "scratch" }
  container_definitions = jsonencode([{
    name            = "runner", image = var.configuration.image_uri, essential = true
    user            = "10001:10001", readonlyRootFilesystem = true, privileged = false
    entryPoint      = ["python", "-I", "/opt/scripts/d0/entrypoint.py"], command = ["read-only"]
    linuxParameters = { capabilities = { drop = ["ALL"] } }
    mountPoints     = [{ sourceVolume = "scratch", containerPath = "/var/scratch", readOnly = false }]
    environment = [
      { name = "D0_DB_HOST", value = var.configuration.db_host },
      { name = "D0_DB_NAME", value = var.configuration.db_name },
      { name = "TMPDIR", value = "/var/scratch" },
      { name = "PYTHONDONTWRITEBYTECODE", value = "1" }
    ]
    secrets = [
      { name = "D0_DB_USERNAME", valueFrom = format("%s:username::", aws_secretsmanager_secret.d0.arn) },
      { name = "D0_DB_PASSWORD", valueFrom = format("%s:password::", aws_secretsmanager_secret.d0.arn) }
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options   = { awslogs-group = aws_cloudwatch_log_group.d0.name, awslogs-region = local.region, awslogs-stream-prefix = "d0" }
    }
  }])
  tags = local.tags
}

resource "aws_ecs_task_definition" "install" {
  skip_destroy = true
  lifecycle { create_before_destroy = true }
  family                   = "ipgo-dev-d0-install"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = var.configuration.bootstrap_execution_role_arn
  task_role_arn            = aws_iam_role.installer.arn
  runtime_platform { operating_system_family = "LINUX" }
  container_definitions = jsonencode([{
    name            = "runner", image = var.configuration.image_uri, essential = true
    user            = "10001:10001", readonlyRootFilesystem = true, privileged = false
    entryPoint      = ["python", "-I", "/opt/scripts/d0/entrypoint.py"], command = ["install"]
    linuxParameters = { capabilities = { drop = ["ALL"] } }
    environment = [
      { name = "D0_DB_HOST", value = var.configuration.db_host },
      { name = "D0_DB_NAME", value = var.configuration.db_name },
      { name = "D0_SECRET_ARN", value = aws_secretsmanager_secret.d0.arn },
      { name = "PYTHONDONTWRITEBYTECODE", value = "1" }
    ]
    secrets = [
      { name = "D0_DB_USERNAME", valueFrom = format("%s:username::", var.configuration.master_secret_arn) },
      { name = "D0_DB_PASSWORD", valueFrom = format("%s:password::", var.configuration.master_secret_arn) }
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options   = { awslogs-group = var.configuration.installation_log_group, awslogs-region = local.region, awslogs-stream-prefix = "d0-install" }
    }
  }])
  tags = local.tags
}

resource "aws_iam_role" "runner" {
  count                = var.runtime_enabled ? 1 : 0
  name                 = "ipgo-dev-d0-runner-oidc"
  max_session_duration = 3600
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = format("arn:aws:iam::%s:oidc-provider/token.actions.githubusercontent.com", local.account) }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = { StringEquals = {
        "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        "token.actions.githubusercontent.com:sub" = local.subject
      } }
    }]
  })
  tags = local.tags
}

resource "aws_iam_role_policy" "runner" {
  count = var.runtime_enabled ? 1 : 0
  role  = aws_iam_role.runner[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid = "RunFixedRevision", Effect = "Allow", Action = "ecs:RunTask", Resource = aws_ecs_task_definition.runtime.arn
        Condition = {
          ArnEquals = { "ecs:cluster" = local.cluster }
          Bool      = { "ecs:enable-execute-command" = "false" }
          StringEquals = {
            "aws:RequestTag/Purpose" = "d0-synthetic", "ecs:task-cpu" = "256", "ecs:task-memory" = "512"
          }
          "ForAllValues:StringEquals" = { "aws:TagKeys" = ["Purpose", "OperationId"] }
        }
      },
      {
        Effect    = "Allow", Action = "ecs:TagResource", Resource = local.tasks
        Condition = { StringEquals = { "ecs:CreateAction" = "RunTask" } }
      },
      {
        Effect    = "Allow", Action = "ecs:DescribeTasks", Resource = local.tasks
        Condition = { ArnEquals = { "ecs:cluster" = local.cluster } }
      },
      {
        Effect    = "Allow", Action = "ecs:StopTask", Resource = local.tasks
        Condition = { ArnEquals = { "ecs:cluster" = local.cluster }, StringEquals = { "aws:ResourceTag/Purpose" = "d0-synthetic" } }
      },
      {
        Effect = "Allow", Action = "ecs:DescribeServices"
        Resource = [
          format("arn:aws:ecs:%s:%s:service/ipgo-dev-cluster/ipgo-dev-onebox-server", local.region, local.account),
          format("arn:aws:ecs:%s:%s:service/ipgo-dev-cluster/ipgo-dev-onebox-ai-api", local.region, local.account)
        ]
      },
      {
        Effect    = "Allow", Action = "iam:PassRole", Resource = aws_iam_role.execution.arn
        Condition = { StringEquals = { "iam:PassedToService" = "ecs-tasks.amazonaws.com" } }
      },
      {
        Effect   = "Allow", Action = "logs:GetLogEvents"
        Resource = format("%s:log-stream:d0/runner/*", aws_cloudwatch_log_group.d0.arn)
      }
    ]
  })
}
