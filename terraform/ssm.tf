resource "aws_ssm_parameter" "slack_token" {
  # Note: SSM parameter names cannot start with "aws" or "ssm" (reserved prefixes).
  name  = "/${var.project_name}/slack-bot-token"
  type  = "SecureString"
  value = "PLACEHOLDER"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "cost_channel_id" {
  name  = "/${var.project_name}/cost-channel-id"
  type  = "String"
  value = "PLACEHOLDER"

  lifecycle {
    ignore_changes = [value]
  }
}
