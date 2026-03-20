#######################################################################
# File: demo.tf
#
# Description:
#   Resources specific to the demo simulation: a CloudWatch Log Group
#   for injected demo logs and a remediation log group where the agent
#   appends actions as log events.
#
# Notes:
#   - The demo log group is separate from the agent execution log group.
#   - The remediation log group preserves full history of all actions.
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

# Log group where the agent appends remediation actions as log events
resource "aws_cloudwatch_log_group" "remediation" {
  name              = "/sre-agent/remediations"
  retention_in_days = 7
}
