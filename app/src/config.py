import os

import boto3

_slack_token_cache: str | None = None


def get_slack_token() -> str:
    global _slack_token_cache
    if _slack_token_cache is None:
        ssm = boto3.client("ssm", region_name=AWS_REGION)
        response = ssm.get_parameter(
            Name=os.environ["SLACK_BOT_TOKEN_PARAM"],
            WithDecryption=True,
        )
        _slack_token_cache = response["Parameter"]["Value"]
    return _slack_token_cache


FEEDS_TABLE_NAME: str = os.environ["FEEDS_TABLE_NAME"]
BEDROCK_MODEL_ID: str = os.environ.get(
    "BEDROCK_MODEL_ID", "anthropic.claude-opus-4-8"
)
AWS_REGION: str = os.environ.get("AWS_REGION", "ap-northeast-1")
