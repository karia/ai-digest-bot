# Drop the legacy feeds table from state WITHOUT destroying it, so existing
# deployments keep their data until `make migrate` copies it into sources.
# Delete the table manually after verifying the migration.
removed {
  from = aws_dynamodb_table.feeds

  lifecycle {
    destroy = false
  }
}

resource "aws_dynamodb_table" "sources" {
  name         = "${var.project_name}-sources"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "title"

  attribute {
    name = "title"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}

resource "aws_dynamodb_table" "advisors" {
  name         = "${var.project_name}-advisors"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "advisor_id"

  attribute {
    name = "advisor_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}

resource "aws_dynamodb_table" "advisor_judgments" {
  name         = "${var.project_name}-advisor-judgments"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "advisor_id"
  range_key    = "run_date"

  attribute {
    name = "advisor_id"
    type = "S"
  }

  attribute {
    name = "run_date"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}
