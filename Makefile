.PHONY: setup config test lint lint-app lint-tf build clean deploy-infra deploy-app deploy deploy-infra-dry deploy-app-dry deploy-dry sources-list sources-add sources-delete migrate update-actions invoke advisors-list advisors-add advisors-delete invoke-advisor

export PATH := $(HOME)/.local/share/mise/shims:$(PATH)

tf_output = $$(terraform -chdir=../terraform output -raw $(1))
APP_TABLE_ENV = SOURCES_TABLE_NAME="$(call tf_output,sources_table_name)" \
	ADVISORS_TABLE_NAME="$(call tf_output,advisors_table_name)" \
	JUDGMENTS_TABLE_NAME="$(call tf_output,judgments_table_name)"
LAMBDA_ENV = LAMBDA_FUNCTION_NAME="$(call tf_output,lambda_function_name)" \
	LAMBDA_ROLE_ARN="$(call tf_output,lambda_role_arn)" \
	$(APP_TABLE_ENV) \
	SLACK_BOT_TOKEN_PARAM="$(call tf_output,slack_token_param_name)"

setup:
	mise install
	uv sync
	prek install

# Usage: make config TFSTATE_BUCKET=<bucket-name>
# Writes the git-ignored backend config that injects the tfstate bucket (kept out of the public repo).
config:
	@test -n "$(TFSTATE_BUCKET)" || { echo "TFSTATE_BUCKET is required"; exit 1; }
	printf 'bucket = "%s"\n' "$(TFSTATE_BUCKET)" > terraform/backend.tfbackend

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
	cd terraform && terraform init -backend-config=backend.tfbackend && terraform apply -auto-approve

deploy-infra-dry:
	cd terraform && terraform init -backend-config=backend.tfbackend && terraform plan

deploy-app: build
	cd app && \
	  $(LAMBDA_ENV) \
	  lambroll deploy --function function.jsonnet --src ../.build

deploy-app-dry: build
	cd app && \
	  $(LAMBDA_ENV) \
	  lambroll diff --function function.jsonnet --src ../.build

deploy: deploy-infra deploy-app

deploy-dry: deploy-infra-dry deploy-app-dry

sources-list:
	cd app && PYTHONPATH=. $(APP_TABLE_ENV) \
	  uv run python ../scripts/manage_sources.py list

# Usage: make sources-add TITLE="技術ダイジェスト" CHANNEL_ID="CXXXX" ITEMS="url1|name 1; url2|name 2|daily" [POSTING_SCHEDULE="月曜と木曜"]
# Items are separated by ";" (names may contain spaces). Append "|daily" to an item to post one threaded reply per JST day.
# Note: full upsert — omitting POSTING_SCHEDULE on re-add resets the schedule to 毎日.
sources-add:
	cd app && PYTHONPATH=. $(APP_TABLE_ENV) \
	  uv run python ../scripts/manage_sources.py add --title "$(TITLE)" --channel-id "$(CHANNEL_ID)" --item "$(ITEMS)" $(if $(POSTING_SCHEDULE),--posting-schedule "$(POSTING_SCHEDULE)")

sources-delete:
	cd app && PYTHONPATH=. $(APP_TABLE_ENV) \
	  uv run python ../scripts/manage_sources.py delete --title "$(TITLE)"

advisors-list:
	cd app && PYTHONPATH=. $(APP_TABLE_ENV) \
	  uv run python ../scripts/manage_advisors.py list

# Usage: make advisors-add ADVISOR_ID=ideco-sbi CHANNEL_ID=CXXXX TITLE="iDeCo 投資判断" \
#          PRODUCTS='[{"isin":"JP90C000H1T1","name":"eMAXIS Slim 全世界株式(オール・カントリー)","category":"全世界株","holding":true,"assoc_fund_cd":"0331418A"}]' \
#          NEWS_FEEDS='[{"url":"https://example.com/rss","name":"市況ニュース"}]' \
#          TRADING_NOTES="スイッチングは指示から完了まで概ね1週間から10日。掛金の配分変更は翌月拠出分から反映。" \
#          [INTERVAL_DAYS=7] [POST_WEEKDAY=FRI]
# Note: full upsert — omitting a field on re-add clears it.
advisors-add:
	cd app && PYTHONPATH=. $(APP_TABLE_ENV) \
	  uv run python ../scripts/manage_advisors.py add --advisor-id "$(ADVISOR_ID)" --channel-id "$(CHANNEL_ID)" --title "$(TITLE)" --products-json '$(PRODUCTS)' --news-feeds-json '$(NEWS_FEEDS)' --trading-notes "$(TRADING_NOTES)" $(if $(INTERVAL_DAYS),--interval-days "$(INTERVAL_DAYS)") $(if $(POST_WEEKDAY),--post-weekday "$(POST_WEEKDAY)")

advisors-delete:
	cd app && PYTHONPATH=. $(APP_TABLE_ENV) \
	  uv run python ../scripts/manage_advisors.py delete --advisor-id "$(ADVISOR_ID)"

# One-off feeds -> sources data migration (idempotent). Optional: TITLE=...
migrate:
	cd app && PYTHONPATH=. $(APP_TABLE_ENV) \
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

invoke-advisor:
	aws lambda invoke \
	  --function-name "$$(terraform -chdir=terraform output -raw lambda_function_name)" \
	  --invocation-type Event \
	  --cli-binary-format raw-in-base64-out \
	  --payload "$$(python3 -c "from datetime import UTC,datetime; print('{\"job\":\"advisor\",\"scheduled_time\":\"' + datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ') + '\"}')")" \
	  /dev/stdout
	@echo "Invoked asynchronously (StatusCode 202 = accepted). Check results in CloudWatch Logs / Slack."

