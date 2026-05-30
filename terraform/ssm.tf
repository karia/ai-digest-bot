resource "aws_ssm_parameter" "slack_token" {
  # SSM parameter names cannot start with "aws" or "ssm" (reserved prefixes),
  # so use the repository name instead of project_name (aws-blog-digest).
  name  = "/ai-digest-bot/slack-bot-token"
  type  = "SecureString"
  value = "PLACEHOLDER"

  lifecycle {
    ignore_changes = [value]
  }
}
