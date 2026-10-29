locals {
  zone_count = length(var.availability_zones)
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = merge(var.tags, { Name = "${var.name_prefix}-vpc" })
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-igw" })
}

resource "aws_subnet" "public" {
  count = local.zone_count

  vpc_id                  = aws_vpc.this.id
  availability_zone       = var.availability_zones[count.index]
  cidr_block              = var.public_subnet_cidrs[count.index]
  map_public_ip_on_launch = true

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-public-${count.index + 1}"
    Tier = "public"
  })
}

resource "aws_subnet" "app" {
  count = local.zone_count

  vpc_id            = aws_vpc.this.id
  availability_zone = var.availability_zones[count.index]
  cidr_block        = var.app_subnet_cidrs[count.index]

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-app-${count.index + 1}"
    Tier = "application"
  })
}

resource "aws_subnet" "database" {
  count = local.zone_count

  vpc_id            = aws_vpc.this.id
  availability_zone = var.availability_zones[count.index]
  cidr_block        = var.database_subnet_cidrs[count.index]

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-database-${count.index + 1}"
    Tier = "database"
  })
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-public-rt" })
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "public" {
  count = local.zone_count

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_eip" "nat" {
  count = var.enable_nat_gateway ? 1 : 0

  domain = "vpc"

  tags = merge(var.tags, { Name = "${var.name_prefix}-nat-eip" })
}

resource "aws_nat_gateway" "this" {
  count = var.enable_nat_gateway ? 1 : 0

  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public[0].id

  tags = merge(var.tags, { Name = "${var.name_prefix}-nat" })

  depends_on = [aws_internet_gateway.this]
}

resource "aws_route_table" "app" {
  count = local.zone_count

  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-app-${count.index + 1}-rt" })
}

resource "aws_route" "app_internet" {
  count = var.enable_nat_gateway ? local.zone_count : 0

  route_table_id         = aws_route_table.app[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this[0].id
}

resource "aws_route_table_association" "app" {
  count = local.zone_count

  subnet_id      = aws_subnet.app[count.index].id
  route_table_id = aws_route_table.app[count.index].id
}

resource "aws_route_table" "database" {
  count = local.zone_count

  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-database-${count.index + 1}-rt" })
}

resource "aws_route_table_association" "database" {
  count = local.zone_count

  subnet_id      = aws_subnet.database[count.index].id
  route_table_id = aws_route_table.database[count.index].id
}

check "subnet_counts_match" {
  assert {
    condition = alltrue([
      length(var.public_subnet_cidrs) == local.zone_count,
      length(var.app_subnet_cidrs) == local.zone_count,
      length(var.database_subnet_cidrs) == local.zone_count,
    ])
    error_message = "Each subnet CIDR list must contain one entry per Availability Zone."
  }
}
