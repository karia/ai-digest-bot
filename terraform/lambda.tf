data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

# Dummy zip for initial deployment (lambroll handles actual code)
data "archive_file" "dummy" {
  type        = "zip"
  output_path = "${path.module}/dummy.zip"

  source {
    content  = "# placeholder"
    filename = "handler.py"
  }
}

resource "aws_iam_role" "lambda_exec" {
  name = "${var.project_name}-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_policy" "lambda_dynamodb" {
  name = "${var.project_name}-lambda-dynamodb"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["dynamodb:Scan", "dynamodb:GetItem"]
      Resource = aws_dynamodb_table.feeds.arn
    }]
  })
}

resource "aws_iam_policy" "lambda_ssm" {
  name = "${var.project_name}-lambda-ssm"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ssm:GetParameter"]
      Resource = aws_ssm_parameter.slack_token.arn
    }, {
      Effect   = "Allow"
      Action   = ["kms:Decrypt"]
      Resource = "arn:aws:kms:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:alias/aws/ssm"
    }]
  })
}

resource "aws_iam_policy" "lambda_bedrock" {
  name = "${var.project_name}-lambda-bedrock"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
      Resource = "arn:aws:bedrock:${data.aws_region.current.name}::foundation-model/${var.bedrock_model_id}"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_dynamodb" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = aws_iam_policy.lambda_dynamodb.arn
}

resource "aws_iam_role_policy_attachment" "lambda_ssm" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = aws_iam_policy.lambda_ssm.arn
}

resource "aws_iam_role_policy_attachment" "lambda_bedrock" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = aws_iam_policy.lambda_bedrock.arn
}

resource "aws_lambda_function" "main" {
  function_name = var.project_name
  role          = aws_iam_role.lambda_exec.arn
  runtime       = "python3.14"
  handler       = "src.handler.lambda_handler"
  timeout       = 300
  memory_size   = 512
  filename      = data.archive_file.dummy.output_path

  environment {
    variables = {
      FEEDS_TABLE_NAME      = aws_dynamodb_table.feeds.name
      SLACK_BOT_TOKEN_PARAM = aws_ssm_parameter.slack_token.name
      BEDROCK_MODEL_ID      = var.bedrock_model_id
    }
  }

  lifecycle {
    ignore_changes = [filename, source_code_hash, layers]
  }
}
