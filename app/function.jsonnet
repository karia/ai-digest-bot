local must_env = std.native('must_env');
local env = std.native('env');

{
  FunctionName: must_env('LAMBDA_FUNCTION_NAME'),
  Description: 'AWS Blog Digest Bot - daily digest via Strands Agent + Bedrock',
  Handler: 'src.handler.lambda_handler',
  MemorySize: 512,
  Role: must_env('LAMBDA_ROLE_ARN'),
  Runtime: 'python3.13',
  Timeout: 300,
  Environment: {
    Variables: {
      FEEDS_TABLE_NAME: must_env('FEEDS_TABLE_NAME'),
      SLACK_BOT_TOKEN_PARAM: must_env('SLACK_BOT_TOKEN_PARAM'),
      BEDROCK_MODEL_ID: env('BEDROCK_MODEL_ID', 'anthropic.claude-opus-4-8'),
    },
  },
}
