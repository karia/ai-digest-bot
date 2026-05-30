.PHONY: setup test lint lint-app lint-tf build clean deploy-infra deploy-app deploy deploy-infra-dry deploy-app-dry deploy-dry feeds-list feeds-add feeds-delete update-actions invoke

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
	uv pip install -r requirements.txt --target .build/
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
	  FEEDS_TABLE_NAME="$$(terraform -chdir=../terraform output -raw feeds_table_name)" \
	  SLACK_BOT_TOKEN_PARAM="$$(terraform -chdir=../terraform output -raw slack_token_param_name)" \
	  lambroll deploy --function function.jsonnet --src ../.build

deploy-app-dry: build
	cd app && \
	  LAMBDA_FUNCTION_NAME="$$(terraform -chdir=../terraform output -raw lambda_function_name)" \
	  LAMBDA_ROLE_ARN="$$(terraform -chdir=../terraform output -raw lambda_role_arn)" \
	  FEEDS_TABLE_NAME="$$(terraform -chdir=../terraform output -raw feeds_table_name)" \
	  SLACK_BOT_TOKEN_PARAM="$$(terraform -chdir=../terraform output -raw slack_token_param_name)" \
	  lambroll diff --function function.jsonnet --src ../.build

deploy: deploy-infra deploy-app

deploy-dry: deploy-infra-dry deploy-app-dry

feeds-list:
	cd app && PYTHONPATH=. FEEDS_TABLE_NAME="$$(terraform -chdir=../terraform output -raw feeds_table_name)" \
	  uv run python ../scripts/manage_feeds.py list

feeds-add:
	cd app && PYTHONPATH=. FEEDS_TABLE_NAME="$$(terraform -chdir=../terraform output -raw feeds_table_name)" \
	  uv run python ../scripts/manage_feeds.py add --feed-url "$(FEED_URL)" --name "$(NAME)" --channel-id "$(CHANNEL_ID)"

feeds-delete:
	cd app && PYTHONPATH=. FEEDS_TABLE_NAME="$$(terraform -chdir=../terraform output -raw feeds_table_name)" \
	  uv run python ../scripts/manage_feeds.py delete --feed-url "$(FEED_URL)"

update-actions:
	pinact -u .github/workflows/ci.yml

invoke:
	aws lambda invoke \
	  --function-name "$$(terraform -chdir=terraform output -raw lambda_function_name)" \
	  --cli-binary-format raw-in-base64-out \
	  --payload "$$(python3 -c "from datetime import UTC,datetime; print('{\"scheduled_time\":\"' + datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ') + '\"}')")" \
	  /dev/stdout
