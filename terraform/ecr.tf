#######################################################################
# File: ecr.tf
#
# Description:
#   ECR repository that stores the agent Docker image and the lifecycle
#   policy that caps storage by expiring images beyond a retention count.
#
# Notes:
#   - MUTABLE tags are intentional; the image_tag variable is bumped
#     to force a rebuild rather than relying on tag immutability.
#   - Scan on push provides passive vulnerability detection without
#     blocking deployments.
#######################################################################

# Stores the SRE agent container image used by the AgentCore runtime
resource "aws_ecr_repository" "agent" {
  name                 = var.ecr_repo_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

# Expires images exceeding the retention count to prevent unbounded storage growth
resource "aws_ecr_lifecycle_policy" "agent" {
  repository = aws_ecr_repository.agent.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = local.ecr_lifecycle_description
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = var.ecr_keep_last
        }
        action = { type = "expire" }
      }
    ]
  })
}