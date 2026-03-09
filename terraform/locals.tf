#######################################################################
# File: locals.tf
#
# Description:
#   Derived values composed from variables and resource attributes.
#   All string interpolation and computed identifiers live here so that
#   resource arguments reference only local.* or var.* directly.
#
# Notes:
#   - Never add inline string compositions inside resource arguments;
#     add a local here instead and reference it.
#######################################################################

# Container image reference built before it is registered with AgentCore
locals {
  image_uri    = "${aws_ecr_repository.agent.repository_url}:${var.image_tag}"
  ecr_registry = aws_ecr_repository.agent.repository_url
}

# Current AWS account identity
data "aws_caller_identity" "current" {}

# IAM identifiers composed from the agent name to keep naming consistent
locals {
  runtime_role_name          = "${var.agent_name}_runtime_role"
  runtime_inline_policy_name = "${var.agent_name}_runtime_inline"
  # :* suffix is required for CloudWatch Logs resource ARNs in IAM policies
  agentcore_log_arn = "arn:aws:logs:${var.region}:*:log-group:/aws/bedrock-agentcore/*:*"
  # IAM role created in iam.tf
  runtime_role_arn = aws_iam_role.runtime.arn
}

# Log group name: use the operator-supplied value or fall back to the
# conventional /aws/bedrock-agentcore/<agent_name> path.
locals {
  resolved_agent_log_group_name = var.agent_log_group_name != "" ? var.agent_log_group_name : "/aws/bedrock-agentcore/${var.agent_name}"
}

# ECR lifecycle policy human-readable description
locals {
  ecr_lifecycle_description = "Keep last ${var.ecr_keep_last} images"
}