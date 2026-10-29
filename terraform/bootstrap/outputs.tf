output "state_bucket_name" {
  description = "S3 bucket used by environment backends."
  value       = aws_s3_bucket.terraform_state.id
}
