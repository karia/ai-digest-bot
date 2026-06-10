import boto3
import pytest
from moto import mock_aws

SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Test Article</title>
      <link>https://example.com/article1</link>
      <description>Test description</description>
      <pubDate>Fri, 30 May 2026 01:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Old Article</title>
      <link>https://example.com/old</link>
      <description>Old description</description>
      <pubDate>Mon, 01 Jan 2026 00:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""

TABLE_NAME = "test-sources"
SSM_PARAM = "/test/slack-bot-token"
SLACK_TOKEN = "xoxb-test-token"

SAMPLE_SOURCE = {
    "title": "Tech Digest",
    "channel_id": "CTEST12345",
    "items": [
        {"url": "https://aws.amazon.com/blogs/aws/feed/", "name": "AWS News Blog"},
    ],
    "inserted_at": "2026-01-01T00:00:00+00:00",
    "updated_at": "2026-01-01T00:00:00+00:00",
}


def _create_sources_table(dynamodb):
    return dynamodb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[{"AttributeName": "title", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "title", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


@pytest.fixture(autouse=True)
def env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-1")
    monkeypatch.setenv("AWS_REGION", "ap-northeast-1")
    monkeypatch.setenv("SOURCES_TABLE_NAME", TABLE_NAME)
    monkeypatch.setenv("SLACK_BOT_TOKEN_PARAM", SSM_PARAM)
    monkeypatch.setenv("BEDROCK_MODEL_ID", "jp.anthropic.claude-sonnet-4-6")


@pytest.fixture
def dynamodb_table():
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="ap-northeast-1")
        table = _create_sources_table(dynamodb)
        table.put_item(Item=SAMPLE_SOURCE)
        yield table


@pytest.fixture
def ssm_parameter():
    with mock_aws():
        ssm = boto3.client("ssm", region_name="ap-northeast-1")
        ssm.put_parameter(
            Name=SSM_PARAM,
            Value=SLACK_TOKEN,
            Type="SecureString",
        )
        yield ssm


@pytest.fixture
def integrated_aws_mock():
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="ap-northeast-1")
        table = _create_sources_table(dynamodb)
        table.put_item(Item=SAMPLE_SOURCE)
        ssm = boto3.client("ssm", region_name="ap-northeast-1")
        ssm.put_parameter(
            Name=SSM_PARAM,
            Value=SLACK_TOKEN,
            Type="SecureString",
        )
        yield


@pytest.fixture
def sample_rss_xml() -> str:
    return SAMPLE_RSS
