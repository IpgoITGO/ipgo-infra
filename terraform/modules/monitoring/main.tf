data "aws_caller_identity" "current" {}

resource "aws_sns_topic" "alerts" {
  name = "${var.name_prefix}-alerts"
  tags = var.tags
}

resource "aws_sns_topic_policy" "alerts" {
  arn = aws_sns_topic.alerts.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowCloudWatchAlarms"
      Effect    = "Allow"
      Principal = { Service = "cloudwatch.amazonaws.com" }
      Action    = "sns:Publish"
      Resource  = aws_sns_topic.alerts.arn
      Condition = {
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
        ArnLike      = { "aws:SourceArn" = "arn:aws:cloudwatch:${var.aws_region}:${data.aws_caller_identity.current.account_id}:alarm:${var.name_prefix}-*" }
      }
    }]
  })
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

locals {
  alb_dimensions = { LoadBalancer = var.alb_arn_suffix }
  target_dimensions = {
    LoadBalancer = var.alb_arn_suffix
    TargetGroup  = var.target_group_arn_suffix
  }
  database_dimensions = { DBInstanceIdentifier = var.database_identifier }
  fixed_alarms = {
    "server-unavailable" = {
      namespace   = "AWS/ApplicationELB", metric = "HealthyHostCount", statistic = "Minimum",
      dimensions  = local.target_dimensions, threshold = 1, comparison = "LessThanThreshold",
      period      = 60, evaluations = 2, missing = "breaching",
      description = "No healthy API target for 2 minutes. Check ECS rollout and /actuator/health."
    }
    "api-errors" = {
      namespace   = "AWS/ApplicationELB", metric = "HTTPCode_Target_5XX_Count", statistic = "Sum",
      dimensions  = local.alb_dimensions, threshold = 5, comparison = "GreaterThanOrEqualToThreshold",
      period      = 300, evaluations = 1, missing = "notBreaching",
      description = "At least 5 backend 5xx responses in 5 minutes. Check server logs and failing requests."
    }
    "alb-errors" = {
      namespace   = "AWS/ApplicationELB", metric = "HTTPCode_ELB_5XX_Count", statistic = "Sum",
      dimensions  = local.alb_dimensions, threshold = 3, comparison = "GreaterThanOrEqualToThreshold",
      period      = 300, evaluations = 1, missing = "notBreaching",
      description = "At least 3 ALB 5xx responses in 5 minutes. Check listeners and healthy targets."
    }
    "database-memory-low" = {
      namespace   = "AWS/RDS", metric = "FreeableMemory", statistic = "Average",
      dimensions  = local.database_dimensions, threshold = 100 * 1024 * 1024, comparison = "LessThanThreshold",
      period      = 300, evaluations = 3, missing = "notBreaching",
      description = "RDS freeable memory below 100 MiB for 15 minutes. Review connections and workload."
    }
    "database-storage-low" = {
      namespace   = "AWS/RDS", metric = "FreeStorageSpace", statistic = "Minimum",
      dimensions  = local.database_dimensions, threshold = 2 * 1024 * 1024 * 1024, comparison = "LessThanThreshold",
      period      = 300, evaluations = 1, missing = "notBreaching",
      description = "RDS free storage below 2 GiB. Inspect growth before changing storage or data."
    }
  }
  service_alarms = merge([
    for key, service in var.services : {
      for metric in ["CPUUtilization", "MemoryUtilization"] : "${key}-${metric == "CPUUtilization" ? "cpu" : "memory"}-high" => {
        namespace   = "AWS/ECS", metric = metric, statistic = "Average",
        dimensions  = { ClusterName = var.cluster_name, ServiceName = service },
        threshold   = 85, comparison = "GreaterThanThreshold",
        period      = 300, evaluations = 3, missing = "notBreaching",
        description = "${service} ${metric} above 85 percent for 15 minutes. Review load and logs."
      }
    }
  ]...)
}

resource "aws_cloudwatch_metric_alarm" "health" {
  for_each = merge({ for key, alarm in local.fixed_alarms : key => alarm if var.enable_legacy_alarms || startswith(key, "database-") }, local.service_alarms)

  alarm_name          = "${var.name_prefix}-${each.key}"
  alarm_description   = each.value.description
  namespace           = each.value.namespace
  metric_name         = each.value.metric
  dimensions          = each.value.dimensions
  statistic           = each.value.statistic
  comparison_operator = each.value.comparison
  threshold           = each.value.threshold
  period              = each.value.period
  evaluation_periods  = each.value.evaluations
  datapoints_to_alarm = each.value.evaluations
  treat_missing_data  = each.value.missing
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = var.tags

  depends_on = [aws_sns_topic_policy.alerts]
}

resource "aws_budgets_budget" "monthly" {
  name         = "${var.name_prefix}-monthly-account-guard"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Account-wide so untagged resources and newly introduced services are covered.
  cost_types {
    include_credit = false
    include_refund = false
    include_tax    = true
    use_blended    = false
  }

  dynamic "notification" {
    for_each = {
      actual_80    = { type = "ACTUAL", threshold = 80 }
      actual_100   = { type = "ACTUAL", threshold = 100 }
      forecast_100 = { type = "FORECASTED", threshold = 100 }
    }
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value.threshold
      threshold_type             = "PERCENTAGE"
      notification_type          = notification.value.type
      subscriber_email_addresses = [var.alert_email]
    }
  }
  tags = var.tags
}
