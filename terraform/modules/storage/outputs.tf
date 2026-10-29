output "bucket_name" {
  description = "Upload bucket name."
  value       = aws_s3_bucket.uploads.id
}

output "bucket_arn" {
  description = "Upload bucket ARN."
  value       = aws_s3_bucket.uploads.arn
}
