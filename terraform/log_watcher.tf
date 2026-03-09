#######################################################################
# File: log_watcher.tf
#
# Description:
#   Lambda function that watches CloudWatch Logs via subscription filter.
#   When ERROR or CRITICAL level logs appear, it invokes the AgentCore
#   runtime to analyze the logs and trigger remediation.
#
# Notes:
#   - Triggered by CloudWatch Logs subscription filter (not by the agent)
#   - Invokes AgentCore runtime directly via bedrock-agentcore-runtime API
#   - Saves AgentCore invocations by filtering before invocation
#######################################################################

# Package the Lambda source code
data "archive_file" "log_watcher_lambda" {
  type        = "zip"
  source_file = "${path.module}/../lambda/log_watcher.py"
  output_path = "${path.module}/.build/log_watcher_lambda.zip"
}

# IAM role assumed by the log_watcher Lambda
data "aws_iam_policy_document" "log_watcher_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "log_watcher_lambda" {
  name               = "${var.agent_name}_log_watcher_lambda_role"
  assume_role_policy = data.aws_iam_policy_document.log_watcher_assume_role.json
}

# Permissions for CloudWatch Logs (execution logs) + AgentCore invocation
data "aws_iam_policy_document" "log_watcher_lambda_policy" {
  statement {
    sid = "CloudWatchLogs"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:${var.region}:*:log-group:/aws/lambda/${var.agent_name}-log-watcher*"]
  }

  statement {
    sid       = "InvokeAgentCore"
    actions   = ["bedrock-agentcore:InvokeAgentRuntime"]
    resources = [aws_bedrockagentcore_agent_runtime.this.agent_runtime_arn]
  }
}

resource "aws_iam_role_policy" "log_watcher_lambda" {
  name   = "${var.agent_name}_log_watcher_lambda_policy"
  role   = aws_iam_role.log_watcher_lambda.id
  policy = data.aws_iam_policy_document.log_watcher_lambda_policy.json
}

# The Lambda function itself
resource "aws_lambda_function" "log_watcher" {
  function_name    = "${var.agent_name}-log-watcher"
  role             = aws_iam_role.log_watcher_lambda.arn
  handler          = "log_watcher.handler"
  runtime          = "python3.12"
  timeout          = 120
  memory_size      = 128
  filename         = data.archive_file.log_watcher_lambda.output_path
  source_code_hash = data.archive_file.log_watcher_lambda.output_base64sha256

  environment {
    variables = {
      AGENTCORE_RUNTIME_ARN = aws_bedrockagentcore_agent_runtime.this.agent_runtime_arn
      AWS_REGION            = var.region
    }
  }

  depends_on = [aws_iam_role_policy.log_watcher_lambda]
}

# CloudWatch Log Group for the Lambda execution logs
resource "aws_cloudwatch_log_group" "log_watcher_lambda" {
  name              = "/aws/lambda/${var.agent_name}-log-watcher"
  retention_in_days = var.agent_log_retention_days
}
