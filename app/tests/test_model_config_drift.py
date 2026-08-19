"""Guard the four places a Bedrock model ID has to be kept in sync.

Only function.jsonnet reaches the deployed Lambda (the Makefile does not
export the model vars, so its env() fallbacks win), while terraform builds
the IAM policy from its own list. A drift between the two deploys a model
the role is not allowed to invoke, which fails at runtime, not at deploy.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
JSONNET = REPO_ROOT / "app" / "function.jsonnet"
VARIABLES_TF = REPO_ROOT / "terraform" / "variables.tf"


def _jsonnet_default(var: str) -> str:
    match = re.search(rf"{var}: env\('{var}', '([^']+)'\)", JSONNET.read_text())
    assert match, f"{var} not found in {JSONNET}"
    return match.group(1)


def _terraform_model_ids() -> list[str]:
    body = re.search(
        r'variable "bedrock_model_ids".*?default = \[(.*?)\]',
        VARIABLES_TF.read_text(),
        re.DOTALL,
    )
    assert body, "bedrock_model_ids default not found"
    return re.findall(r'"([^"]+)"', body.group(1))


@pytest.mark.parametrize("var", ["BEDROCK_MODEL_ID", "BEDROCK_ADVICE_MODEL_ID"])
def test_jsonnet_default_is_granted_by_the_iam_policy(var: str) -> None:
    assert _jsonnet_default(var) in _terraform_model_ids()


@pytest.mark.parametrize("var", ["BEDROCK_MODEL_ID", "BEDROCK_ADVICE_MODEL_ID"])
def test_jsonnet_default_matches_the_python_default(var: str) -> None:
    from src import config

    assert _jsonnet_default(var) == getattr(config, var)


def test_the_two_agents_do_not_share_a_model() -> None:
    assert _jsonnet_default("BEDROCK_MODEL_ID") != _jsonnet_default(
        "BEDROCK_ADVICE_MODEL_ID"
    )
