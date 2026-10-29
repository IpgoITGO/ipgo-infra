output "jobs_queue_arn" {
  value = aws_sqs_queue.jobs.arn
}

output "jobs_queue_url" {
  value = aws_sqs_queue.jobs.id
}

output "results_queue_arn" {
  value = aws_sqs_queue.results.arn
}

output "results_queue_url" {
  value = aws_sqs_queue.results.id
}

output "jobs_dlq_arn" {
  value = aws_sqs_queue.jobs_dlq.arn
}

output "results_dlq_arn" {
  value = aws_sqs_queue.results_dlq.arn
}
