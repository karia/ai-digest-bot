.PHONY: setup test lint lint-app lint-tf build clean deploy-infra deploy-app deploy deploy-infra-dry deploy-app-dry deploy-dry sources-list sources-add sources-delete migrate update-actions invoke

export PATH := $(HOME)/.local/share/mise/shims:$(PATH)

setup:
	mise install
	uv sync
	uv run pre-commit install

test:
	uv run pytest

lint: lint-app lint-tf

lint-app:
	uv run ruff check app/
	uv run ruff format --check app/
	uv run mypy app/src/

lint-tf:
	cd terraform && terraform fmt -check -recursive
	cd terraform && terraform validate
	cd terraform && tflint --config=.tflint.hcl

build:
	uv export --no-dev --no-hashes -o requirements.txt
	rm -rf .build
	# Cross-platform install for the Lambda runtime (arm64 Linux); local OS/arch must not leak in.
	# sgmllib3k is sdist-only but pure Python, so it is the sole source-build exception.
	uv pip install -r requirements.txt --target .build/ \
	  --python-platform aarch64-manylinux2014 --only-binary :all: --no-binary sgmllib3k
	cp -r app/src .build/src

clean:
	rm -rf .build requirements.txt function.zip

deploy-infra:
	cd terraform && terraform init && terraform apply -auto-approve

deploy-infra-dry:
	cd terraform && terraform init && terraform plan

deploy-app: build
	cd app && \
	  LAMBDA_FUNCTION_NAME="$$(terraform -chdir=../terraform output -raw lambda_function_name)" \
	  LAMBDA_ROLE_ARN="$$(terraform -chdir=../terraform output -raw lambda_role_arn)" \
	  SOURCES_TABLE_NAME="$$(terraform -chdir=../terraform output -raw sources_table_name)" \
	  SLACK_BOT_TOKEN_PARAM="$$(terraform -chdir=../terraform output -raw slack_token_param_name)" \
	  lambroll deploy --function function.jsonnet --src ../.build

deploy-app-dry: build
	cd app && \
	  LAMBDA_FUNCTION_NAME="$$(terraform -chdir=../terraform output -raw lambda_function_name)" \
	  LAMBDA_ROLE_ARN="$$(terraform -chdir=../terraform output -raw lambda_role_arn)" \
	  SOURCES_TABLE_NAME="$$(terraform -chdir=../terraform output -raw sources_table_name)" \
	  SLACK_BOT_TOKEN_PARAM="$$(terraform -chdir=../terraform output -raw slack_token_param_name)" \
	  lambroll diff --function function.jsonnet --src ../.build

deploy: deploy-infra deploy-app

deploy-dry: deploy-infra-dry deploy-app-dry

sources-list:
	cd app && PYTHONPATH=. SOURCES_TABLE_NAME="$$(terraform -chdir=../terraform output -raw sources_table_name)" \
	  uv run python ../scripts/manage_sources.py list

# Usage: make sources-add TITLE="技術ダイジェスト" CHANNEL_ID="CXXXX" ITEMS="url1|name1 url2|name2"
sources-add:
	cd app && PYTHONPATH=. SOURCES_TABLE_NAME="$$(terraform -chdir=../terraform output -raw sources_table_name)" \
	  uv run python ../scripts/manage_sources.py add --title "$(TITLE)" --channel-id "$(CHANNEL_ID)" $(foreach it,$(ITEMS),--item "$(it)")

sources-delete:
	cd app && PYTHONPATH=. SOURCES_TABLE_NAME="$$(terraform -chdir=../terraform output -raw sources_table_name)" \
	  uv run python ../scripts/manage_sources.py delete --title "$(TITLE)"

# One-off feeds -> sources data migration (idempotent). Optional: TITLE=...
migrate:
	cd app && PYTHONPATH=. SOURCES_TABLE_NAME="$$(terraform -chdir=../terraform output -raw sources_table_name)" \
	  MIGRATE_TITLE="$(TITLE)" \
	  uv run python -m src.migrate

update-actions:
	pinact -u .github/workflows/ci.yml

invoke:
	aws lambda invoke \
	  --function-name "$$(terraform -chdir=terraform output -raw lambda_function_name)" \
	  --invocation-type Event \
	  --cli-binary-format raw-in-base64-out \
	  --payload "$$(python3 -c "from datetime import UTC,datetime; print('{\"scheduled_time\":\"' + datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ') + '\"}')")" \
	  /dev/stdout
	@echo "Invoked asynchronously (StatusCode 202 = accepted). Check results in CloudWatch Logs / Slack."
