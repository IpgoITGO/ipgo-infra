resource "aws_db_subnet_group" "this" {
  name       = "${var.name_prefix}-postgres"
  subnet_ids = var.subnet_ids

  tags = merge(var.tags, { Name = "${var.name_prefix}-postgres" })
}

resource "aws_db_instance" "this" {
  identifier = "${var.name_prefix}-postgres"

  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class

  db_name                     = var.database_name
  username                    = var.master_username
  manage_master_user_password = true
  port                        = 5432

  allocated_storage     = var.allocated_storage
  max_allocated_storage = var.max_allocated_storage
  storage_type          = "gp3"
  storage_encrypted     = true

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = var.security_group_ids
  publicly_accessible    = false
  multi_az               = var.multi_az

  backup_retention_period    = var.backup_retention_period
  auto_minor_version_upgrade = true
  copy_tags_to_snapshot      = true
  deletion_protection        = var.deletion_protection
  skip_final_snapshot        = var.skip_final_snapshot
  final_snapshot_identifier  = var.skip_final_snapshot ? null : "${var.name_prefix}-postgres-final"

  apply_immediately = false

  tags = merge(var.tags, { Name = "${var.name_prefix}-postgres" })
}
