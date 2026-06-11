import os
from datetime import timedelta, timezone

import boto3

# JST has no DST, so a fixed +9 offset is correct and avoids a tzdata dependency.
JST = timezone(timedelta(hours=9))

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


SOURCES_TABLE_NAME: str = os.environ["SOURCES_TABLE_NAME"]
BEDROCK_MODEL_ID: str = os.environ.get(
    "BEDROCK_MODEL_ID", "jp.anthropic.claude-sonnet-4-6"
)
AWS_REGION: str = os.environ.get("AWS_REGION", "ap-northeast-1")
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
