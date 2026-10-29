locals {
  services = toset([
    "server",
    "ai",
    "database-bootstrap",
    "database-migrate",
    "database-verify",
  ])

  database_secret_arns = {
    database-bootstrap = var.database_bootstrap_secret_arns
    database-migrate   = var.database_migrate_secret_arns
    database-verify    = var.database_verify_secret_arns
  }
}

data "aws_iam_policy_document" "ecs_task_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  for_each = local.services

  name               = "${var.name_prefix}-${each.key}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume.json

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "execution" {
  for_each = local.services

  role       = aws_iam_role.execution[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "server_secrets" {
  count = length(var.server_secret_arns) > 0 ? 1 : 0

  statement {
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = var.server_secret_arns
  }
}

resource "aws_iam_role_policy" "server_secrets" {
  count = length(var.server_secret_arns) > 0 ? 1 : 0

  name   = "secrets"
  role   = aws_iam_role.execution["server"].id
  policy = data.aws_iam_policy_document.server_secrets[0].json
}

data "aws_iam_policy_document" "ai_secrets" {
  count = length(var.ai_secret_arns) > 0 ? 1 : 0

  statement {
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = var.ai_secret_arns
  }
}

resource "aws_iam_role_policy" "ai_secrets" {
  count = length(var.ai_secret_arns) > 0 ? 1 : 0

  name   = "secrets"
  role   = aws_iam_role.execution["ai"].id
  policy = data.aws_iam_policy_document.ai_secrets[0].json
}

data "aws_iam_policy_document" "database_secrets" {
  for_each = {
    for service, secret_arns in local.database_secret_arns : service => secret_arns
    if length(secret_arns) > 0
  }

  statement {
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = each.value
  }
}

resource "aws_iam_role_policy" "database_secrets" {
  for_each = data.aws_iam_policy_document.database_secrets

  name   = "secrets"
  role   = aws_iam_role.execution[each.key].id
  policy = each.value.json
}

resource "aws_iam_role" "server_task" {
  name               = "${var.name_prefix}-server-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume.json

  tags = var.tags
}

data "aws_iam_policy_document" "server_task" {
  statement {
    sid       = "ListUploads"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [var.upload_bucket_arn]
  }

  statement {
    sid    = "ReadWriteUploads"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:PutObject",
      "s3:AbortMultipartUpload",
    ]
    resources = ["${var.upload_bucket_arn}/*"]
  }

  statement {
    sid       = "SendJobs"
    effect    = "Allow"
    actions   = ["sqs:GetQueueAttributes", "sqs:SendMessage"]
    resources = [var.jobs_queue_arn]
  }

  statement {
    sid    = "ConsumeResults"
    effect = "Allow"
    actions = [
      "sqs:ChangeMessageVisibility",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:ReceiveMessage",
    ]
    resources = [var.results_queue_arn]
  }

  statement {
    sid       = "SendEmail"
    effect    = "Allow"
    actions   = ["ses:SendEmail", "ses:SendRawEmail"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "server_task" {
  name   = "application-access"
  role   = aws_iam_role.server_task.id
  policy = data.aws_iam_policy_document.server_task.json
}

resource "aws_iam_role" "ai_task" {
  name               = "${var.name_prefix}-ai-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume.json

  tags = var.tags
}

data "aws_iam_policy_document" "ai_task" {
  statement {
    sid       = "ListUploads"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [var.upload_bucket_arn]
  }

  statement {
    sid       = "ReadUploads"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${var.upload_bucket_arn}/*"]
  }

  statement {
    sid    = "ConsumeJobs"
    effect = "Allow"
    actions = [
      "sqs:ChangeMessageVisibility",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:ReceiveMessage",
    ]
    resources = [var.jobs_queue_arn]
  }

  statement {
    sid       = "SendResults"
    effect    = "Allow"
    actions   = ["sqs:GetQueueAttributes", "sqs:SendMessage"]
    resources = [var.results_queue_arn]
  }
}

resource "aws_iam_role_policy" "ai_task" {
  name   = "application-access"
  role   = aws_iam_role.ai_task.id
  policy = data.aws_iam_policy_document.ai_task.json
}
