#######################################################################
# File: cloudwatch.tf
#
# Description:
#   CloudWatch Log Group used by the SRE agent container to write
#   structured JSON execution logs (prompts, tool calls, answers,
#   exceptions). The log group name is passed to the container via
#   the AGENT_LOG_GROUP environment variable in agentcore.tf.
#
# Notes:
#   - Retention is 1 day by default (configurable via
#     var.agent_log_retention_days).
#   - The name defaults to /aws/bedrock-agentcore/<agent_name> so it
#     stays inside the namespace the runtime role already allows.
#######################################################################

# Destination log group where the agent writes structured audit/execution logs
resource "aws_cloudwatch_log_group" "agent_execution" {
  name              = local.resolved_agent_log_group_name
  retention_in_days = var.agent_log_retention_days
}
