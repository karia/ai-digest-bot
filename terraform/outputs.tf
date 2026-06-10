output "lambda_function_name" {
  description = "Lambda function name for lambroll deployment"
  value       = aws_lambda_function.main.function_name
}

output "lambda_role_arn" {
  description = "Lambda execution role ARN for lambroll deployment"
  value       = aws_iam_role.lambda_exec.arn
}

output "sources_table_name" {
  description = "DynamoDB sources table name"
  value       = aws_dynamodb_table.sources.name
}

output "slack_token_param_name" {
  description = "SSM parameter name for Slack Bot Token"
  value       = aws_ssm_parameter.slack_token.name
}
