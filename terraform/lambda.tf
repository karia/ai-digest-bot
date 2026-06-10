data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

locals {
  # Strip the inference-profile region prefix (e.g. "jp.") to get the base
  # foundation model name used in foundation-model ARNs.
  bedrock_foundation_model = replace(var.bedrock_model_id, "jp.", "")
}

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
      Effect   = "Allow"
      Action   = ["dynamodb:Scan", "dynamodb:GetItem"]
      Resource = aws_dynamodb_table.sources.arn
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
      Resource = "arn:aws:kms:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:alias/aws/ssm"
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
      Resource = [
        # The inference profile the app invokes
        "arn:aws:bedrock:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:inference-profile/${var.bedrock_model_id}",
        # Foundation models the jp profile routes to (ap-northeast-1 / ap-northeast-3)
        "arn:aws:bedrock:ap-northeast-1::foundation-model/${local.bedrock_foundation_model}",
        "arn:aws:bedrock:ap-northeast-3::foundation-model/${local.bedrock_foundation_model}",
      ]
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
  filename      = data.archive_file.dummy.output_path

  # runtime and handler are required at creation time, but the source of truth
  # for all runtime settings (runtime, handler, timeout, memory_size,
  # environment, tracing_config) is app/function.jsonnet, applied by lambroll.
  # These are placeholders for the initial create; see ignore_changes below.
  runtime = "python3.14"
  handler = "src.handler.lambda_handler"

  lifecycle {
    ignore_changes = [
      filename,
      source_code_hash,
      layers,
      runtime,
      handler,
      timeout,
      memory_size,
      environment,
      tracing_config,
    ]
  }
}
