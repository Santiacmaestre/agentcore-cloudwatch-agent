#######################################################################
# File: demo.tf
#
# Description:
#   Resources specific to the demo simulation: a CloudWatch Log Group
#   for injected demo logs and an SSM parameter that the remediation
#   Lambda writes to. Also provisions the log group variable for the
#   inject_demo_logs.py script.
#
# Notes:
#   - The demo log group is separate from the agent execution log group.
#   - The SSM parameter is created with a placeholder value; the Lambda
#     overwrites it when triggered by the agent.
#######################################################################

# Log group where inject_demo_logs.py writes simulated application logs
resource "aws_cloudwatch_log_group" "demo_app_logs" {
  name              = var.demo_log_group_name
  retention_in_days = 7
}

# Subscription filter that sends ERROR/CRITICAL logs to the log_watcher Lambda
resource "aws_cloudwatch_log_subscription_filter" "log_watcher" {
  name            = "${var.agent_name}_log_watcher_subscription"
  log_group_name  = aws_cloudwatch_log_group.demo_app_logs.name
  filter_pattern  = "{ ($.level = \"ERROR\") || ($.level = \"CRITICAL\") }"
  destination_arn = aws_lambda_function.log_watcher.arn

  depends_on = [aws_lambda_permission.cloudwatch_invoke_log_watcher]
}

# Allow CloudWatch Logs to invoke the log_watcher Lambda
resource "aws_lambda_permission" "cloudwatch_invoke_log_watcher" {
  statement_id  = "AllowCloudWatchLogsInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.log_watcher.function_name
  principal     = "logs.amazonaws.com"
  source_arn    = "${aws_cloudwatch_log_group.demo_app_logs.arn}:*"
}

# Seed SSM parameter – the agent overwrites this when writing remediation actions
resource "aws_ssm_parameter" "remediation_latest" {
  name        = "/sre-agent/actions/latest"
  type        = "String"
  value       = "{\"status\": \"no_issues_detected\"}"
  description = "Latest remediation action written by the SRE agent"

  lifecycle {
    ignore_changes = [value, description]
  }
}
