import os
from datetime import timedelta, timezone

import boto3

# JST has no DST, so a fixed +9 offset is correct and avoids a tzdata dependency.
JST = timezone(timedelta(hours=9))

_ssm_cache: dict[str, str] = {}


def _get_ssm_parameter(env_var: str) -> str:
    """Read the SSM parameter whose name is held in ``env_var``.

    Cached per module load so a warm Lambda invocation makes no extra call.

    Args:
        env_var: Environment variable holding the SSM parameter name.

    Returns:
        The parameter value, decrypted for SecureString parameters.
    """
    name = os.environ[env_var]
    if name not in _ssm_cache:
        ssm = boto3.client("ssm", region_name=AWS_REGION)
        response = ssm.get_parameter(Name=name, WithDecryption=True)
        _ssm_cache[name] = response["Parameter"]["Value"]
    return _ssm_cache[name]


def get_slack_token() -> str:
    return _get_ssm_parameter("SLACK_BOT_TOKEN_PARAM")


def get_cost_channel_id() -> str:
    # Kept in SSM rather than the repo: this repository is public and a channel
    # ID identifies a private workspace destination.
    return _get_ssm_parameter("COST_CHANNEL_ID_PARAM")


SOURCES_TABLE_NAME: str = os.environ["SOURCES_TABLE_NAME"]
ADVISORS_TABLE_NAME: str = os.environ["ADVISORS_TABLE_NAME"]
JUDGMENTS_TABLE_NAME: str = os.environ["JUDGMENTS_TABLE_NAME"]
# Digest work is summarization against fetched text, so it runs on the lighter
# model. The advisor's BUY/SELL/HOLD call is the one judgment worth the heavier
# one, so it has its own setting.
BEDROCK_MODEL_ID: str = os.environ.get(
    "BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-5"
)
BEDROCK_ADVICE_MODEL_ID: str = os.environ.get(
    "BEDROCK_ADVICE_MODEL_ID", "global.anthropic.claude-opus-5"
)
AWS_REGION: str = os.environ.get("AWS_REGION", "ap-northeast-1")
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
