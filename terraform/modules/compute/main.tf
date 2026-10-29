resource "aws_ecr_repository" "server" {
  name                 = "${var.name_prefix}/server"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = var.tags
}

resource "aws_ecr_repository" "ai" {
  name                 = "${var.name_prefix}/ai"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = var.tags
}

resource "aws_ecr_lifecycle_policy" "repositories" {
  for_each = {
    server = aws_ecr_repository.server.name
    ai     = aws_ecr_repository.ai.name
  }

  repository = each.value
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the most recent 30 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 30
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_ecs_cluster" "this" {
  name = "${var.name_prefix}-cluster"

  setting {
    name  = "containerInsights"
    value = "enhanced"
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "server" {
  name              = "/ipgo/${var.name_prefix}/server"
  retention_in_days = var.log_retention_days

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "ai" {
  name              = "/ipgo/${var.name_prefix}/ai"
  retention_in_days = var.log_retention_days

  tags = var.tags
}

resource "aws_service_discovery_private_dns_namespace" "this" {
  name        = "${var.name_prefix}.internal"
  description = "Ipgo ECS Service Connect namespace"
  vpc         = var.vpc_id

  tags = var.tags
}

resource "aws_lb" "this" {
  name                       = substr("${var.name_prefix}-alb", 0, 32)
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [var.alb_security_group_id]
  subnets                    = var.public_subnet_ids
  drop_invalid_header_fields = true
  enable_deletion_protection = false

  tags = var.tags
}

resource "aws_lb_target_group" "server" {
  name        = substr("${var.name_prefix}-server", 0, 32)
  port        = 8080
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id

  deregistration_delay = 30

  health_check {
    enabled             = true
    healthy_threshold   = 2
    interval            = 30
    matcher             = "200"
    path                = var.server_health_check_path
    timeout             = 5
    unhealthy_threshold = 3
  }

  tags = var.tags
}

resource "aws_lb_listener" "https" {
  count = var.certificate_arn == null ? 0 : 1

  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.server.arn
  }
}

resource "aws_lb_listener" "http_redirect" {
  count = var.certificate_arn == null ? 0 : 1

  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}
