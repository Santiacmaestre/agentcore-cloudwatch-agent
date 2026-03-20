#######################################################################
# File: outputs.tf
#
# Description:
#   Exposes key identifiers produced by this module so callers and
#   operators can reference them without inspecting the state file.
#
# Notes:
#   - agent_runtime_arn is the value required by invoke.py and any
#     downstream integration that calls the AgentCore runtime directly.
#######################################################################

# Allows external tooling to push additional images to the same repository
output "ecr_repository_url" {
  value = aws_ecr_repository.agent.repository_url
}

# Identifies the exact image registered with the AgentCore runtime
output "image_uri" {
  value = local.image_uri
}

# Required by invoke.py to construct the AgentCore invocation endpoint
output "agent_runtime_arn" {
  value = aws_bedrockagentcore_agent_runtime.this.agent_runtime_arn
}

# IAM role assumed by the AgentCore runtime at execution time
output "runtime_role_arn" {
  value = aws_iam_role.runtime.arn
}

# Memory resource ID passed to the runtime and used for cross-session context
output "memory_id" {
  value = aws_bedrockagentcore_memory.this.id
}

# Log group where the agent writes structured execution/audit logs
output "agent_execution_log_group" {
  value = aws_cloudwatch_log_group.agent_execution.name
}

# Demo log group for injected simulated application logs
output "demo_log_group" {
  value = aws_cloudwatch_log_group.demo_app_logs.name
}

# Log watcher Lambda function name (triggered by CloudWatch Logs subscription filter)
output "log_watcher_lambda_name" {
  value = aws_lambda_function.log_watcher.function_name
}

# CloudWatch Log Group where the agent writes remediation actions
output "remediation_log_group" {
  value = aws_cloudwatch_log_group.remediation.name
}

# Endpoint ARN for programmatic invocation of the agent runtime
output "agent_runtime_endpoint_arn" {
  value = aws_bedrockagentcore_agent_runtime_endpoint.this.agent_runtime_endpoint_arn
}

