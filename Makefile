.PHONY: setup test lint lint-app lint-tf build deploy-infra deploy-app deploy deploy-infra-dry deploy-app-dry deploy-dry seed update-actions

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
	pip install -r requirements.txt -t .build/ --quiet
	cp -r app/src/* .build/
	cd .build && zip -r ../function.zip .

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
	  lambroll deploy --function function.jsonnet

deploy-app-dry: build
	cd app && \
	  LAMBDA_FUNCTION_NAME="$$(terraform -chdir=../terraform output -raw lambda_function_name)" \
	  LAMBDA_ROLE_ARN="$$(terraform -chdir=../terraform output -raw lambda_role_arn)" \
	  FEEDS_TABLE_NAME="$$(terraform -chdir=../terraform output -raw feeds_table_name)" \
	  SLACK_BOT_TOKEN_PARAM="$$(terraform -chdir=../terraform output -raw slack_token_param_name)" \
	  lambroll diff --function function.jsonnet

deploy: deploy-infra deploy-app

deploy-dry: deploy-infra-dry deploy-app-dry

seed:
	uv run python scripts/seed_feeds.py

update-actions:
	pinact -u .github/workflows/ci.yml
