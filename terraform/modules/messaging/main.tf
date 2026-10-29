resource "aws_sqs_queue" "jobs_dlq" {
  name                      = "${var.name_prefix}-jobs-dlq"
  message_retention_seconds = 1209600
  kms_master_key_id         = "alias/aws/sqs"

  tags = var.tags
}

resource "aws_sqs_queue" "results_dlq" {
  name                      = "${var.name_prefix}-results-dlq"
  message_retention_seconds = 1209600
  kms_master_key_id         = "alias/aws/sqs"

  tags = var.tags
}

resource "aws_sqs_queue" "jobs" {
  name                       = "${var.name_prefix}-jobs"
  receive_wait_time_seconds  = 20
  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = 345600
  kms_master_key_id          = "alias/aws/sqs"

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.jobs_dlq.arn
    maxReceiveCount     = var.max_receive_count
  })

  tags = var.tags
}

resource "aws_sqs_queue" "results" {
  name                       = "${var.name_prefix}-results"
  receive_wait_time_seconds  = 20
  visibility_timeout_seconds = 120
  message_retention_seconds  = 345600
  kms_master_key_id          = "alias/aws/sqs"

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.results_dlq.arn
    maxReceiveCount     = var.max_receive_count
  })

  tags = var.tags
}

resource "aws_sqs_queue_redrive_allow_policy" "jobs_dlq" {
  queue_url = aws_sqs_queue.jobs_dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.jobs.arn]
  })
}

resource "aws_sqs_queue_redrive_allow_policy" "results_dlq" {
  queue_url = aws_sqs_queue.results_dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.results.arn]
  })
}
