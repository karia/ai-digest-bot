resource "aws_iam_role" "scheduler" {
  name = "${var.project_name}-scheduler"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "scheduler_invoke_lambda" {
  name = "invoke-lambda"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["lambda:InvokeFunction"]
      Resource = aws_lambda_function.main.arn
    }]
  })
}

resource "aws_scheduler_schedule" "daily_digest" {
  name       = "${var.project_name}-daily"
  group_name = "default"

  flexible_time_window {
    mode = "OFF"
  }

  # JST 09:00 (timezone Asia/Tokyo)
  schedule_expression          = "cron(0 9 * * ? *)"
  schedule_expression_timezone = "Asia/Tokyo"

  target {
    arn      = aws_lambda_function.main.arn
    role_arn = aws_iam_role.scheduler.arn
    # NOTE: do not use jsonencode() here. It escapes < and > to < / >,
    # which breaks EventBridge Scheduler's <aws.scheduler.scheduled-time> context
    # attribute substitution (the literal placeholder would reach the Lambda).
    input = "{\"scheduled_time\": \"<aws.scheduler.scheduled-time>\"}"
  }
}

resource "aws_scheduler_schedule" "advisor" {
  name       = "${var.project_name}-advisor"
  group_name = "default"

  flexible_time_window {
    mode = "OFF"
  }

  # JST 17:00 (timezone Asia/Tokyo). Runs daily; posting cadence is decided
  # in-app from interval_days plus the Slack history check, so shortening the
  # interval needs no infra change.
  schedule_expression          = "cron(0 17 * * ? *)"
  schedule_expression_timezone = "Asia/Tokyo"

  target {
    arn      = aws_lambda_function.main.arn
    role_arn = aws_iam_role.scheduler.arn
    # NOTE: do not use jsonencode() here. It escapes < and >, which breaks
    # the <aws.scheduler.scheduled-time> context attribute substitution.
    input = "{\"job\": \"advisor\", \"scheduled_time\": \"<aws.scheduler.scheduled-time>\"}"
  }
}
