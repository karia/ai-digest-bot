local must_env = std.native('must_env');
local env = std.native('env');

{
  Architectures: ['arm64'],
  FunctionName: must_env('LAMBDA_FUNCTION_NAME'),
  Description: 'AI Digest Bot - tech digest + investment advisor via Strands Agent + Bedrock',
  Handler: 'src.handler.lambda_handler',
  MemorySize: 512,
  Role: must_env('LAMBDA_ROLE_ARN'),
  Runtime: 'python3.14',
  // 900 = Lambda max. The advisor job needs the headroom: N sequential NAV
  // fetches plus an agent loop that can run 8-20 turns (FX lookups, news
  // feed crawl, per-product nav_fetch, per-product reason). A shorter
  // timeout can hard-kill mid-thread, leaving a parent post with no product
  // replies and no put_judgments, which should_post then treats as "already
  // posted today" until interval_days elapses. Costs nothing when unused;
  // the digest job finishes well under this.
  Timeout: 900,
  TracingConfig: {
    Mode: 'Active',
  },
  Environment: {
    Variables: {
      SOURCES_TABLE_NAME: must_env('SOURCES_TABLE_NAME'),
      ADVISORS_TABLE_NAME: must_env('ADVISORS_TABLE_NAME'),
      JUDGMENTS_TABLE_NAME: must_env('JUDGMENTS_TABLE_NAME'),
      SLACK_BOT_TOKEN_PARAM: must_env('SLACK_BOT_TOKEN_PARAM'),
      BEDROCK_MODEL_ID: env('BEDROCK_MODEL_ID', 'jp.anthropic.claude-sonnet-4-6'),
      LOG_LEVEL: env('LOG_LEVEL', 'INFO'),
    },
  },
}
