#######################################################################
# File: iam.tf
#
# Description:
#   IAM role and inline policy that the AgentCore runtime assumes at
#   execution time. Grants least-privilege access to CloudWatch Logs
#   Insights, Bedrock model invocation, and ECR image pulling.
#
# Notes:
#   - The CloudWatch write permissions cover only the AgentCore log
#     group prefix so the runtime can emit its own execution logs.
#   - ECR GetAuthorizationToken is account-scoped and cannot be
#     restricted to a single repository.
#######################################################################

# Allows the AgentCore service principal to assume the runtime execution role
data "aws_iam_policy_document" "agentcore_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
  }
}

# Execution role assumed by the AgentCore runtime during agent invocations
resource "aws_iam_role" "runtime" {
  name               = local.runtime_role_name
  assume_role_policy = data.aws_iam_policy_document.agentcore_assume_role.json
}

# Defines the permission boundaries for CloudWatch, Bedrock, and ECR access
data "aws_iam_policy_document" "runtime_policy" {
  statement {
    sid = "CloudWatchLogsInsights"
    actions = [
      "logs:StartQuery",
      "logs:GetQueryResults",
      "logs:StopQuery",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
      "logs:DescribeQueryDefinitions",
      "logs:DescribeSubscriptionFilters",
      "logs:GetLogEvents",
      "logs:FilterLogEvents",
      "logs:GetLogGroupFields",
      "logs:GetLogRecord",
      "logs:ListLogAnomalyDetectors",
      "logs:ListTagsForResource",
    ]
    resources = ["*"]
  }

  statement {
    sid = "CloudWatchLogsWrite"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams"
    ]
    resources = [local.agentcore_log_arn]
  }

  statement {
    sid = "BedrockInvoke"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
      "bedrock:Converse",
      "bedrock:ConverseStream",
    ]
    resources = ["*"]
  }

  statement {
    sid = "ECRPull"
    actions = [
      "ecr:GetAuthorizationToken",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer"
    ]
    resources = ["*"]
  }

  statement {
    sid       = "STSAssumeRole"
    actions   = ["sts:AssumeRole"]
    resources = ["*"]
  }

  # Allows the runtime to read from and write to the AgentCore Memory resource
  statement {
    sid = "AgentCoreMemory"
    actions = [
      "bedrock-agentcore:CreateEvent",
      "bedrock-agentcore:ListMemories",
      "bedrock-agentcore:GetMemory",
    ]
    resources = ["arn:aws:bedrock-agentcore:${var.region}:*:memory/${aws_bedrockagentcore_memory.this.id}"]
  }

  # Allows the agent to write remediation actions to the remediation log group
  statement {
    sid = "RemediationLogsWrite"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams",
    ]
    resources = ["${aws_cloudwatch_log_group.remediation.arn}:*"]
  }
}

# Attaches the permissions policy inline to avoid a separate managed policy resource
resource "aws_iam_role_policy" "runtime_inline" {
  name   = local.runtime_inline_policy_name
  role   = aws_iam_role.runtime.id
  policy = data.aws_iam_policy_document.runtime_policy.json
}