resource "aws_ssm_parameter" "slack_token" {
  name  = "/${var.project_name}/slack-bot-token"
  type  = "SecureString"
  value = "PLACEHOLDER"

  lifecycle {
    ignore_changes = [value]
  }
}
