# BYOC deployment — MemoryVault into the CUSTOMER's AWS account.
# "Paste keys" = your AWS creds + `terraform apply`. Provisions the vault in
# the customer's own cloud (RDS Postgres+pgvector, KMS key they own, ECS
# Fargate service), so their memory and keys never leave their account.
#
#   cd deploy/terraform
#   terraform init
#   terraform apply -var="db_password=..." -var="image=ghcr.io/you/memoryvault:latest"

terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

variable "region"      { default = "us-east-1" }
variable "db_password" { sensitive = true }
variable "image"       { description = "MemoryVault container image" }
variable "name"        { default = "memoryvault" }

provider "aws" { region = var.region }

# --- the customer-owned encryption key ("we can't read your data") ---
resource "aws_kms_key" "vault" {
  description             = "MemoryVault data key (customer-owned)"
  deletion_window_in_days = 14
  enable_key_rotation     = true
}
resource "aws_kms_alias" "vault" {
  name          = "alias/${var.name}"
  target_key_id = aws_kms_key.vault.key_id
}

# --- Postgres + pgvector (RDS) ---
resource "aws_db_instance" "vault" {
  identifier            = "${var.name}-db"
  engine                = "postgres"
  engine_version        = "16.3"
  instance_class        = "db.t3.medium"
  allocated_storage     = 50
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.vault.arn
  db_name               = "memoryvault"
  username              = "mvadmin"
  password              = var.db_password
  skip_final_snapshot   = false
  final_snapshot_identifier = "${var.name}-final"
  backup_retention_period   = 14
  deletion_protection       = true
}

# --- ECS Fargate service running the container ---
resource "aws_ecs_cluster" "vault" { name = "${var.name}-cluster" }

resource "aws_ecs_task_definition" "vault" {
  family                   = var.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.exec.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions = jsonencode([{
    name  = var.name
    image = var.image
    portMappings = [{ containerPort = 8000 }]
    environment = [
      { name = "DATABASE_URL", value = "postgres://mvadmin:${var.db_password}@${aws_db_instance.vault.endpoint}/memoryvault" },
      { name = "MV_ENCRYPT", value = "1" },
      { name = "MV_KMS_PROVIDER", value = "aws" },
      { name = "MV_KMS_KEY_ID", value = aws_kms_key.vault.arn },
    ]
  }])
}

# IAM: task may use the customer's KMS key, nothing else.
resource "aws_iam_role" "task" {
  name               = "${var.name}-task"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}
resource "aws_iam_role" "exec" {
  name               = "${var.name}-exec"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}
data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals { type = "Service", identifiers = ["ecs-tasks.amazonaws.com"] }
  }
}
resource "aws_iam_role_policy" "kms" {
  role   = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
      Resource = aws_kms_key.vault.arn
    }]
  })
}

output "kms_key_arn" { value = aws_kms_key.vault.arn }
output "db_endpoint" { value = aws_db_instance.vault.endpoint }
output "cluster"     { value = aws_ecs_cluster.vault.name }
