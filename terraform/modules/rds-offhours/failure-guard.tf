resource "aws_iam_role" "failure_guard" {
  name               = "${local.name}-failure-guard"
  assume_role_policy = jsonencode(local.assume.lambda)
}
resource "aws_iam_role_policy" "failure_guard" {
  role = aws_iam_role.failure_guard.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [local.log_statement,
    { Effect = "Allow", Action = "dynamodb:PutItem", Resource = aws_dynamodb_table.ledger.arn, Condition = { "ForAllValues:StringEquals" = { "dynamodb:LeadingKeys" = ["STOP_BLOCKED"] } } }
  ] })
}
resource "aws_lambda_function" "failure_guard" {
  function_name    = "${local.name}-failure-guard"
  role             = aws_iam_role.failure_guard.arn
  handler          = "failure_guard.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.runtime.output_path
  source_code_hash = data.archive_file.runtime.output_base64sha256
  timeout          = 20
  environment { variables = { CONFIG = jsonencode({ ledger_table = aws_dynamodb_table.ledger.name, state_machine_arn = local.runtime_config.state_machine_arn }) } }
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.runtime.name
  }
  depends_on = [aws_iam_role_policy.failure_guard]
}
resource "aws_cloudwatch_event_rule" "workflow_failure" {
  name = "${local.name}-workflow-failure"
  event_pattern = jsonencode({ source = ["aws.states"], "detail-type" = ["Step Functions Execution Status Change"], detail = {
    stateMachineArn = [local.runtime_config.state_machine_arn], status = ["FAILED", "TIMED_OUT", "ABORTED"]
  } })
}
resource "aws_cloudwatch_event_target" "failure_guard" {
  rule = aws_cloudwatch_event_rule.workflow_failure.name
  arn  = aws_lambda_function.failure_guard.arn
}
resource "aws_lambda_permission" "failure_guard" {
  statement_id  = "OnlyOwnWorkflowFailureRule"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.failure_guard.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.workflow_failure.arn
}
