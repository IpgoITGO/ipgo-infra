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

resource "aws_ecr_repository" "database" {
  name                 = "${var.name_prefix}/database"
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
    server   = aws_ecr_repository.server.name
    ai       = aws_ecr_repository.ai.name
    database = aws_ecr_repository.database.name
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

resource "aws_cloudwatch_log_group" "database" {
  name              = "/ipgo/${var.name_prefix}/database"
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

resource "aws_ecs_task_definition" "server" {
  family                   = "${var.name_prefix}-server"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = var.server_execution_role_arn
  task_role_arn            = var.server_task_role_arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([
    {
      name      = "server"
      image     = "${aws_ecr_repository.server.repository_url}:bootstrap"
      essential = true
      portMappings = [{
        name          = "http"
        containerPort = 8080
        hostPort      = 8080
        protocol      = "tcp"
        appProtocol   = "http"
      }]
      environment = [
        { name = "AWS_REGION", value = var.aws_region },
        { name = "IPGO_AI_BASE_URL", value = "http://ai:8000" },
        { name = "IPGO_JOBS_QUEUE_URL", value = var.jobs_queue_url },
        { name = "IPGO_RESULTS_QUEUE_URL", value = var.results_queue_url },
        { name = "IPGO_UPLOAD_BUCKET", value = var.upload_bucket_name },
        { name = "IPGO_UPLOAD_STORAGE", value = "s3" },
        { name = "SERVER_PORT", value = "8080" },
        { name = "SERVER_SERVLET_SESSION_COOKIE_SECURE", value = "true" },
        { name = "SPRING_FLYWAY_ENABLED", value = "false" },
      ]
      secrets = [
        { name = "SPRING_DATASOURCE_PASSWORD", valueFrom = "${var.server_database_secret_arn}:password::" },
        { name = "SPRING_DATASOURCE_URL", valueFrom = "${var.server_database_secret_arn}:url::" },
        { name = "SPRING_DATASOURCE_USERNAME", valueFrom = "${var.server_database_secret_arn}:username::" },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.server.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "server"
        }
      }
    }
  ])

  tags = var.tags
}

resource "aws_ecs_task_definition" "database_bootstrap" {
  family                   = "${var.name_prefix}-database-bootstrap"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = var.database_bootstrap_execution_role_arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([{
    name      = "database"
    image     = "${aws_ecr_repository.database.repository_url}:bootstrap"
    essential = true
    command   = ["bootstrap"]
    environment = [
      { name = "DB_HOST", value = var.database_host },
      { name = "DB_PORT", value = tostring(var.database_port) },
      { name = "DB_NAME", value = var.database_name },
    ]
    secrets = [
      { name = "DB_ADMIN_USERNAME", valueFrom = "${var.database_master_secret_arn}:username::" },
      { name = "DB_ADMIN_PASSWORD", valueFrom = "${var.database_master_secret_arn}:password::" },
      { name = "IPGO_MIGRATOR_PASSWORD", valueFrom = "${var.database_migrator_secret_arn}:password::" },
      { name = "IPGO_SERVER_PASSWORD", valueFrom = "${var.server_database_secret_arn}:password::" },
      { name = "IPGO_AI_READER_PASSWORD", valueFrom = "${var.ai_database_secret_arn}:password::" },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.database.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "bootstrap"
      }
    }
  }])

  tags = var.tags
}

resource "aws_ecs_task_definition" "database_migrate" {
  family                   = "${var.name_prefix}-database-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = var.database_migrate_execution_role_arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([{
    name      = "database"
    image     = "${aws_ecr_repository.database.repository_url}:bootstrap"
    essential = true
    command   = ["migrate"]
    environment = [
      { name = "DB_HOST", value = var.database_host },
      { name = "DB_PORT", value = tostring(var.database_port) },
      { name = "DB_NAME", value = var.database_name },
    ]
    secrets = [
      { name = "DB_USERNAME", valueFrom = "${var.database_migrator_secret_arn}:username::" },
      { name = "DB_PASSWORD", valueFrom = "${var.database_migrator_secret_arn}:password::" },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.database.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "migrate"
      }
    }
  }])

  tags = var.tags
}

resource "aws_ecs_task_definition" "database_verify" {
  family                   = "${var.name_prefix}-database-verify"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = var.database_verify_execution_role_arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([{
    name      = "database"
    image     = "${aws_ecr_repository.database.repository_url}:bootstrap"
    essential = true
    command   = ["verify"]
    environment = [
      { name = "DB_HOST", value = var.database_host },
      { name = "DB_PORT", value = tostring(var.database_port) },
      { name = "DB_NAME", value = var.database_name },
    ]
    secrets = [
      { name = "IPGO_SERVER_USERNAME", valueFrom = "${var.server_database_secret_arn}:username::" },
      { name = "IPGO_SERVER_PASSWORD", valueFrom = "${var.server_database_secret_arn}:password::" },
      { name = "IPGO_AI_READER_USERNAME", valueFrom = "${var.ai_database_secret_arn}:username::" },
      { name = "IPGO_AI_READER_PASSWORD", valueFrom = "${var.ai_database_secret_arn}:password::" },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.database.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "verify"
      }
    }
  }])

  tags = var.tags
}

resource "aws_ecs_task_definition" "ai_api" {
  family                   = "${var.name_prefix}-ai-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = var.ai_execution_role_arn
  task_role_arn            = var.ai_task_role_arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([
    {
      name      = "ai-api"
      image     = "${aws_ecr_repository.ai.repository_url}:bootstrap"
      essential = true
      command   = ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
      portMappings = [{
        name          = "http"
        containerPort = 8000
        hostPort      = 8000
        protocol      = "tcp"
        appProtocol   = "http"
      }]
      environment = [
        { name = "AWS_REGION", value = var.aws_region },
        { name = "ENGINE_MODE", value = "real" },
        { name = "IPGO_JOBS_QUEUE_URL", value = var.jobs_queue_url },
        { name = "IPGO_RESULTS_QUEUE_URL", value = var.results_queue_url },
        { name = "IPGO_UPLOAD_BUCKET", value = var.upload_bucket_name },
      ]
      secrets = [
        { name = "DATABASE_URL", valueFrom = "${var.ai_database_secret_arn}:url::" },
        # LLM insight runs only in the FastAPI service. The batch worker must not receive this key.
        { name = "OPENAI_API_KEY", valueFrom = var.ai_openai_secret_arn },
      ]
      healthCheck = {
        command = [
          "CMD-SHELL",
          "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)\"",
        ]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ai.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "api"
        }
      }
    }
  ])

  tags = var.tags
}

resource "aws_ecs_task_definition" "ai_worker" {
  family                   = "${var.name_prefix}-ai-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = var.ai_execution_role_arn
  task_role_arn            = var.ai_task_role_arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([
    {
      name      = "ai-worker"
      image     = "${aws_ecr_repository.ai.repository_url}:bootstrap"
      essential = true
      command   = ["python", "-m", "app.worker"]
      environment = [
        { name = "AWS_REGION", value = var.aws_region },
        { name = "ENGINE_MODE", value = "real" },
        { name = "IPGO_JOBS_QUEUE_URL", value = var.jobs_queue_url },
        { name = "IPGO_RESULTS_QUEUE_URL", value = var.results_queue_url },
        { name = "IPGO_UPLOAD_BUCKET", value = var.upload_bucket_name },
      ]
      secrets = [
        { name = "DATABASE_URL", valueFrom = "${var.ai_database_secret_arn}:url::" },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ai.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "worker"
        }
      }
    }
  ])

  tags = var.tags
}

resource "aws_ecs_service" "server" {
  name                               = "${var.name_prefix}-server"
  cluster                            = aws_ecs_cluster.this.id
  task_definition                    = aws_ecs_task_definition.server.arn
  desired_count                      = var.server_desired_count
  launch_type                        = "FARGATE"
  platform_version                   = "LATEST"
  health_check_grace_period_seconds  = 60
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  enable_execute_command             = false

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.task_subnet_ids
    security_groups  = [var.server_security_group_id]
    assign_public_ip = var.task_assign_public_ip
  }

  dynamic "load_balancer" {
    for_each = var.certificate_arn == null ? [] : [aws_lb_target_group.server.arn]

    content {
      target_group_arn = load_balancer.value
      container_name   = "server"
      container_port   = 8080
    }
  }

  service_connect_configuration {
    enabled   = true
    namespace = aws_service_discovery_private_dns_namespace.this.arn
  }

  lifecycle {
    ignore_changes = [desired_count, task_definition]
  }

  # ECS rejects a target group until an ALB listener has associated it with
  # the load balancer. With no certificate, both the listener and this
  # service's load-balancer attachment intentionally remain absent.
  depends_on = [aws_lb_listener.https]

  tags = var.tags
}

resource "aws_ecs_service" "ai_api" {
  name                               = "${var.name_prefix}-ai-api"
  cluster                            = aws_ecs_cluster.this.id
  task_definition                    = aws_ecs_task_definition.ai_api.arn
  desired_count                      = var.ai_api_desired_count
  launch_type                        = "FARGATE"
  platform_version                   = "LATEST"
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  enable_execute_command             = false

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.task_subnet_ids
    security_groups  = [var.ai_security_group_id]
    assign_public_ip = var.task_assign_public_ip
  }

  service_connect_configuration {
    enabled   = true
    namespace = aws_service_discovery_private_dns_namespace.this.arn

    service {
      port_name      = "http"
      discovery_name = "ai"

      client_alias {
        dns_name = "ai"
        port     = 8000
      }
    }
  }

  lifecycle {
    ignore_changes = [desired_count, task_definition]
  }

  tags = var.tags
}

resource "aws_ecs_service" "ai_worker" {
  name                               = "${var.name_prefix}-ai-worker"
  cluster                            = aws_ecs_cluster.this.id
  task_definition                    = aws_ecs_task_definition.ai_worker.arn
  desired_count                      = var.ai_worker_desired_count
  launch_type                        = "FARGATE"
  platform_version                   = "LATEST"
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  enable_execute_command             = false

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.task_subnet_ids
    security_groups  = [var.ai_security_group_id]
    assign_public_ip = var.task_assign_public_ip
  }

  lifecycle {
    ignore_changes = [desired_count, task_definition]
  }

  tags = var.tags
}
