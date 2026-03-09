#######################################################################
# File: agentcore.tf
#
# Description:
#   Defines the Bedrock AgentCore runtime that runs the CloudWatch Logs
#   SRE agent container. Wires the ECR image, IAM execution role, and
#   environment configuration into a single deployable runtime unit.
#
# Notes:
#   - network_mode PUBLIC is required for the runtime to reach Bedrock
#     and CloudWatch APIs without a VPC NAT gateway.
#   - Environment variables are the contract between Terraform inputs
#     and the Python agent running inside the container.
#######################################################################

# Runs the SRE agent container on AgentCore with access to Bedrock and CloudWatch
resource "aws_bedrockagentcore_agent_runtime" "this" {
  agent_runtime_name = var.agent_name
  role_arn           = local.runtime_role_arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = local.image_uri
    }
  }

  network_configuration {
    network_mode = "PUBLIC"
  }

  environment_variables = {
    AWS_REGION      = var.region
    MODEL_ID        = var.model_id
    MAX_RESULT_CHARS = tostring(var.max_result_chars)
    MEMORY_ID       = aws_bedrockagentcore_memory.this.id
    MEMORY_ACTOR_ID = var.memory_actor_id
    AGENT_LOG_GROUP = aws_cloudwatch_log_group.agent_execution.name
  }

  depends_on = [
    aws_iam_role_policy.runtime_inline,
    null_resource.docker_build_push,
    aws_bedrockagentcore_memory.this,
    aws_cloudwatch_log_group.agent_execution,
  ]
}

# Exposes the runtime as an invocable endpoint for the log_watcher Lambda
resource "aws_bedrockagentcore_agent_runtime_endpoint" "this" {
  name             = "${replace(var.agent_name, "-", "_")}_endpoint"
  agent_runtime_id = aws_bedrockagentcore_agent_runtime.this.agent_runtime_id
  description      = "Endpoint for Lambda-driven invocation of the SRE agent"

  depends_on = [aws_bedrockagentcore_agent_runtime.this]
}