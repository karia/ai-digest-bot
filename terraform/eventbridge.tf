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

resource "aws_scheduler_schedule" "cost" {
  name       = "${var.project_name}-cost"
  group_name = "default"

  flexible_time_window {
    mode = "OFF"
  }

  # JST 23:00. AWS bills by UTC days, so the day being reported closes at
  # 09:00 JST; running fourteen hours later leaves Cost Explorer time to
  # settle it (observed: about eight hours). An earlier slot would report a
  # day that is still accruing.
  schedule_expression          = "cron(0 23 * * ? *)"
  schedule_expression_timezone = "Asia/Tokyo"

  target {
    arn      = aws_lambda_function.main.arn
    role_arn = aws_iam_role.scheduler.arn
    # NOTE: do not use jsonencode() here; it breaks context attribute substitution.
    input = "{\"job\": \"cost\", \"scheduled_time\": \"<aws.scheduler.scheduled-time>\"}"
  }
}

resource "aws_scheduler_schedule" "advisor" {
  name       = "${var.project_name}-advisor"
  group_name = "default"

  flexible_time_window {
    mode = "OFF"
  }

  # JST 17:00 daily. Which day actually posts is decided in-app from the
  # advisor's post_weekday, so a run that fails on the target day is retried by
  # the next day's invocation instead of waiting a whole week. Pinning the day
  # here instead would remove that retry.
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
