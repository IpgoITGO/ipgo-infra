locals {
  project     = "ipgo"
  environment = "dev"
  name_prefix = "${local.project}-${local.environment}"

  common_tags = {
    Project     = local.project
    Environment = local.environment
    ManagedBy   = "terraform"
    Repository  = "IpgoITGO/ipgo-infra"
  }
}

module "network" {
  source = "../../modules/network"

  name_prefix           = local.name_prefix
  vpc_cidr              = "10.40.0.0/16"
  availability_zones    = var.availability_zones
  public_subnet_cidrs   = ["10.40.0.0/24", "10.40.1.0/24"]
  app_subnet_cidrs      = ["10.40.10.0/24", "10.40.11.0/24"]
  database_subnet_cidrs = ["10.40.20.0/24", "10.40.21.0/24"]
  enable_nat_gateway    = var.enable_nat_gateway
  tags                  = local.common_tags
}

resource "aws_security_group" "alb" {
  name        = "${local.name_prefix}-alb"
  description = "Public HTTPS entry point"
  vpc_id      = module.network.vpc_id

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-alb" })
}

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
  description       = "HTTP redirect after TLS listener is enabled"
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  description       = "Public HTTPS"
}

resource "aws_security_group" "server" {
  name        = "${local.name_prefix}-server"
  description = "Spring Boot ECS tasks"
  vpc_id      = module.network.vpc_id

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-server" })
}

resource "aws_vpc_security_group_egress_rule" "alb_to_server" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.server.id
  from_port                    = 8080
  to_port                      = 8080
  ip_protocol                  = "tcp"
  description                  = "Forward requests to Spring Boot"
}

resource "aws_vpc_security_group_ingress_rule" "server_from_alb" {
  security_group_id            = aws_security_group.server.id
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = 8080
  to_port                      = 8080
  ip_protocol                  = "tcp"
  description                  = "Spring Boot from ALB"
}

resource "aws_vpc_security_group_egress_rule" "server_outbound" {
  security_group_id = aws_security_group.server.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "Database, AWS services, FastAPI and SES"
}

resource "aws_security_group" "ai" {
  name        = "${local.name_prefix}-ai"
  description = "FastAPI ECS tasks"
  vpc_id      = module.network.vpc_id

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-ai" })
}

resource "aws_vpc_security_group_ingress_rule" "ai_from_server" {
  security_group_id            = aws_security_group.ai.id
  referenced_security_group_id = aws_security_group.server.id
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
  description                  = "Internal engine HTTP from Spring Boot"
}

resource "aws_vpc_security_group_egress_rule" "ai_outbound" {
  security_group_id = aws_security_group.ai.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "Read-only database, AWS services and LLM provider"
}

resource "aws_security_group" "database" {
  name        = "${local.name_prefix}-database"
  description = "Private PostgreSQL"
  vpc_id      = module.network.vpc_id

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-database" })
}

resource "aws_security_group" "database_tasks" {
  name        = "${local.name_prefix}-database-tasks"
  description = "One-off database bootstrap, migration and verification tasks"
  vpc_id      = module.network.vpc_id

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-database-tasks" })
}

resource "aws_vpc_security_group_egress_rule" "database_tasks_outbound" {
  security_group_id = aws_security_group.database_tasks.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "PostgreSQL and AWS services for one-off database tasks"
}

resource "aws_vpc_security_group_ingress_rule" "database_from_tasks" {
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = aws_security_group.database_tasks.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  description                  = "One-off database tasks"
}

resource "aws_vpc_security_group_ingress_rule" "database_from_server" {
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = aws_security_group.server.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  description                  = "Spring Boot database access"
}

resource "aws_vpc_security_group_ingress_rule" "database_from_ai" {
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = aws_security_group.ai.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  description                  = "FastAPI read-only database access"
}

module "storage" {
  source = "../../modules/storage"

  name_prefix = local.name_prefix
  tags        = local.common_tags
}

module "messaging" {
  source = "../../modules/messaging"

  name_prefix = local.name_prefix
  tags        = local.common_tags
}

module "database" {
  source = "../../modules/database"

  name_prefix             = local.name_prefix
  subnet_ids              = module.network.database_subnet_ids
  security_group_ids      = [aws_security_group.database.id]
  engine_version          = var.db_engine_version
  instance_class          = var.db_instance_class
  multi_az                = false
  deletion_protection     = true
  skip_final_snapshot     = false
  backup_retention_period = 7
  tags                    = local.common_tags
}

resource "aws_secretsmanager_secret" "server_database" {
  name                    = "/ipgo/dev/server-database"
  description             = "Spring application database credentials; value is provisioned out of band"
  recovery_window_in_days = 7

  tags = local.common_tags
}

resource "aws_secretsmanager_secret" "ai_database" {
  name                    = "/ipgo/dev/ai-database"
  description             = "FastAPI read-only database credentials; value is provisioned out of band"
  recovery_window_in_days = 7

  tags = local.common_tags
}

resource "aws_secretsmanager_secret" "database_migrator" {
  name                    = "/ipgo/dev/database-migrator"
  description             = "Flyway database credentials; value is provisioned out of band"
  recovery_window_in_days = 7

  tags = local.common_tags
}

resource "aws_secretsmanager_secret" "ai_openai" {
  name                    = "/ipgo/dev/ai-openai-api-key"
  description             = "OpenAI API key for FastAPI; value is provisioned out of band"
  recovery_window_in_days = 7

  tags = local.common_tags
}

module "compute" {
  source = "../../modules/compute"

  name_prefix                           = local.name_prefix
  aws_region                            = var.aws_region
  vpc_id                                = module.network.vpc_id
  public_subnet_ids                     = module.network.public_subnet_ids
  task_subnet_ids                       = var.enable_nat_gateway ? module.network.app_subnet_ids : module.network.public_subnet_ids
  task_assign_public_ip                 = !var.enable_nat_gateway
  alb_security_group_id                 = aws_security_group.alb.id
  server_security_group_id              = aws_security_group.server.id
  ai_security_group_id                  = aws_security_group.ai.id
  server_execution_role_arn             = module.identity.server_execution_role_arn
  server_task_role_arn                  = module.identity.server_task_role_arn
  ai_execution_role_arn                 = module.identity.ai_execution_role_arn
  ai_task_role_arn                      = module.identity.ai_task_role_arn
  database_bootstrap_execution_role_arn = module.identity.database_bootstrap_execution_role_arn
  database_migrate_execution_role_arn   = module.identity.database_migrate_execution_role_arn
  database_verify_execution_role_arn    = module.identity.database_verify_execution_role_arn
  database_host                         = module.database.address
  database_port                         = module.database.port
  database_name                         = "ipgo"
  database_master_secret_arn            = module.database.master_secret_arn
  database_migrator_secret_arn          = aws_secretsmanager_secret.database_migrator.arn
  server_database_secret_arn            = aws_secretsmanager_secret.server_database.arn
  ai_database_secret_arn                = aws_secretsmanager_secret.ai_database.arn
  ai_openai_secret_arn                  = aws_secretsmanager_secret.ai_openai.arn
  upload_bucket_name                    = module.storage.bucket_name
  jobs_queue_url                        = module.messaging.jobs_queue_url
  results_queue_url                     = module.messaging.results_queue_url
  server_desired_count                  = var.server_desired_count
  ai_api_desired_count                  = var.ai_api_desired_count
  ai_worker_desired_count               = var.ai_worker_desired_count
  certificate_arn                       = var.certificate_arn
  tags                                  = local.common_tags
}

module "identity" {
  source = "../../modules/identity"

  name_prefix       = local.name_prefix
  upload_bucket_arn = module.storage.bucket_arn
  jobs_queue_arn    = module.messaging.jobs_queue_arn
  results_queue_arn = module.messaging.results_queue_arn
  server_secret_arns = [
    aws_secretsmanager_secret.server_database.arn,
  ]
  ai_secret_arns = [
    aws_secretsmanager_secret.ai_database.arn,
    aws_secretsmanager_secret.ai_openai.arn,
  ]
  database_bootstrap_secret_arns = [
    module.database.master_secret_arn,
    aws_secretsmanager_secret.database_migrator.arn,
    aws_secretsmanager_secret.server_database.arn,
    aws_secretsmanager_secret.ai_database.arn,
  ]
  database_migrate_secret_arns = [
    aws_secretsmanager_secret.database_migrator.arn,
  ]
  database_verify_secret_arns = [
    aws_secretsmanager_secret.server_database.arn,
    aws_secretsmanager_secret.ai_database.arn,
  ]
  tags = local.common_tags
}
