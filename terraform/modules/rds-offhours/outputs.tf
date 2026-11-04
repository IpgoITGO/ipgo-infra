output "review" {
  value = {
    state_machine_arn = aws_sfn_state_machine.controller.arn
    ledger_table      = aws_dynamodb_table.ledger.name
    schedules         = { for k, s in aws_scheduler_schedule.rds : k => { arn = s.arn, state = s.state } }
    audit_task_arn    = aws_ecs_task_definition.audit.arn
    stop_enabled      = var.stop_enabled
  }
}
